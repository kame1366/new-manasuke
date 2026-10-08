from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ai.errors import (
    AIInteractionAlreadyRunningError,
)
from db.connection import (
    connect,
    transaction,
)
from domain.enums import (
    AttemptStage,
    AttemptStatus,
)
from domain.time_rules import (
    UTC,
    from_db_utc,
    to_db_utc,
)
from planning.attempt_errors import (
    AttemptNotActiveError,
    AttemptStageError,
)


AI_OPERATION_LEARNING_POLICY = (
    "LEARNING_POLICY_GENERATION"
)

AI_OPERATION_PLANNING = (
    "PLANNING_GENERATION"
)

AI_STATUS_RUNNING = "RUNNING"
AI_STATUS_SUCCEEDED = "SUCCEEDED"
AI_STATUS_FAILED = "FAILED"


@dataclass(
    frozen=True,
    slots=True,
)
class AIInteractionRecord:
    id: int

    participant_id: str
    attempt_id: int | None

    operation_type: str

    created_at: datetime

    prompt_version: str
    model_name: str

    structured_output_json: (
        str | None
    )

    status: str
    error_type: str | None


class AIInteractionRepository:
    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(
            db_path
        )

    # =====================================================
    # AI①
    # =====================================================

    def start(
        self,
        *,
        participant_id: str,
        operation_type: str,
        prompt_version: str,
        model_name: str,
    ) -> int:
        with transaction(
            self._db_path
        ) as connection:
            existing = (
                connection.execute(
                    """
                    SELECT id
                    FROM ai_interactions
                    WHERE participant_id = ?
                      AND operation_type = ?
                      AND status = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (
                        participant_id,
                        operation_type,
                        AI_STATUS_RUNNING,
                    ),
                ).fetchone()
            )

            if existing is not None:
                raise (
                    AIInteractionAlreadyRunningError(
                        "AI interaction is already "
                        "running for participant"
                    )
                )

            cursor = connection.execute(
                """
                INSERT INTO ai_interactions (
                    participant_id,
                    attempt_id,
                    operation_type,
                    created_at,
                    prompt_version,
                    model_name,
                    structured_output_json,
                    status,
                    error_type
                )
                VALUES (
                    ?,
                    NULL,
                    ?,
                    ?,
                    ?,
                    ?,
                    NULL,
                    ?,
                    NULL
                )
                """,
                (
                    participant_id,
                    operation_type,
                    to_db_utc(
                        datetime.now(
                            UTC
                        )
                    ),
                    prompt_version,
                    model_name,
                    AI_STATUS_RUNNING,
                ),
            )

            interaction_id = (
                cursor.lastrowid
            )

            if interaction_id is None:
                raise RuntimeError(
                    "failed to create "
                    "AIInteraction"
                )

            return int(
                interaction_id
            )

    # =====================================================
    # AI②
    # =====================================================

    def start_for_attempt(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        prompt_version: str,
        model_name: str,
        now: datetime,
    ) -> int:
        """
        AI②はattempt_id必須。

        OpenAI呼び出し前に短Transactionで
        RUNNING監査レコードだけ作る。
        """
        with transaction(
            self._db_path
        ) as connection:
            attempt = connection.execute(
                """
                SELECT
                    status,
                    stage
                FROM plan_generation_attempts
                WHERE participant_id = ?
                  AND id = ?
                """,
                (
                    participant_id,
                    attempt_id,
                ),
            ).fetchone()

            if attempt is None:
                raise AttemptNotActiveError(
                    "Attempt not found"
                )

            if (
                attempt["status"]
                != AttemptStatus
                .IN_PROGRESS
                .value
            ):
                raise AttemptNotActiveError(
                    "Attempt is not IN_PROGRESS"
                )

            if (
                attempt["stage"]
                != AttemptStage
                .AI_PLANNING
                .value
            ):
                raise AttemptStageError(
                    "AI② may start only in "
                    "AI_PLANNING stage"
                )

            running = connection.execute(
                """
                SELECT id
                FROM ai_interactions
                WHERE participant_id = ?
                  AND attempt_id = ?
                  AND operation_type = ?
                  AND status = ?
                LIMIT 1
                """,
                (
                    participant_id,
                    attempt_id,
                    AI_OPERATION_PLANNING,
                    AI_STATUS_RUNNING,
                ),
            ).fetchone()

            if running is not None:
                raise (
                    AIInteractionAlreadyRunningError(
                        "Planning AI is already "
                        "running for Attempt"
                    )
                )

            cursor = connection.execute(
                """
                INSERT INTO ai_interactions (
                    participant_id,
                    attempt_id,
                    operation_type,
                    created_at,
                    prompt_version,
                    model_name,
                    structured_output_json,
                    status,
                    error_type
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL)
                """,
                (
                    participant_id,
                    attempt_id,
                    AI_OPERATION_PLANNING,
                    to_db_utc(
                        now
                    ),
                    prompt_version,
                    model_name,
                    AI_STATUS_RUNNING,
                ),
            )

            interaction_id = (
                cursor.lastrowid
            )

            if interaction_id is None:
                raise RuntimeError(
                    "failed to create "
                    "planning AIInteraction"
                )

            return int(
                interaction_id
            )

    @staticmethod
    def mark_succeeded_for_attempt_in_transaction(
        connection: sqlite3.Connection,
        *,
        participant_id: str,
        attempt_id: int,
        interaction_id: int,
        structured_output_json: str,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE ai_interactions
            SET
                status = ?,
                structured_output_json = ?,
                error_type = NULL
            WHERE participant_id = ?
              AND attempt_id = ?
              AND id = ?
              AND operation_type = ?
              AND status = ?
            """,
            (
                AI_STATUS_SUCCEEDED,
                structured_output_json,
                participant_id,
                attempt_id,
                interaction_id,
                AI_OPERATION_PLANNING,
                AI_STATUS_RUNNING,
            ),
        )

        if cursor.rowcount != 1:
            raise RuntimeError(
                "RUNNING planning AIInteraction "
                "not found"
            )

    # =====================================================
    # Generic completion
    # =====================================================

    @staticmethod
    def mark_succeeded_in_transaction(
        connection: sqlite3.Connection,
        *,
        participant_id: str,
        interaction_id: int,
        structured_output_json: str,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE ai_interactions
            SET
                status = ?,
                structured_output_json = ?,
                error_type = NULL
            WHERE participant_id = ?
              AND id = ?
              AND status = ?
            """,
            (
                AI_STATUS_SUCCEEDED,
                structured_output_json,
                participant_id,
                interaction_id,
                AI_STATUS_RUNNING,
            ),
        )

        if cursor.rowcount != 1:
            raise RuntimeError(
                "RUNNING AIInteraction "
                "not found"
            )

    def mark_succeeded(
        self,
        *,
        participant_id: str,
        interaction_id: int,
        structured_output_json: str,
    ) -> None:
        with transaction(
            self._db_path
        ) as connection:
            self.mark_succeeded_in_transaction(
                connection,
                participant_id=participant_id,
                interaction_id=interaction_id,
                structured_output_json=(
                    structured_output_json
                ),
            )

    def mark_failed(
        self,
        *,
        participant_id: str,
        interaction_id: int,
        error_type: str,
    ) -> None:
        with transaction(
            self._db_path
        ) as connection:
            cursor = connection.execute(
                """
                UPDATE ai_interactions
                SET
                    status = ?,
                    error_type = ?
                WHERE participant_id = ?
                  AND id = ?
                  AND status = ?
                """,
                (
                    AI_STATUS_FAILED,
                    error_type,
                    participant_id,
                    interaction_id,
                    AI_STATUS_RUNNING,
                ),
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    "RUNNING AIInteraction "
                    "not found"
                )

    # =====================================================
    # Read
    # =====================================================

    def get_by_id(
        self,
        *,
        participant_id: str,
        interaction_id: int,
    ) -> AIInteractionRecord | None:
        connection = connect(
            self._db_path
        )

        try:
            row = connection.execute(
                """
                SELECT
                    id,
                    participant_id,
                    attempt_id,
                    operation_type,
                    created_at,
                    prompt_version,
                    model_name,
                    structured_output_json,
                    status,
                    error_type
                FROM ai_interactions
                WHERE participant_id = ?
                  AND id = ?
                """,
                (
                    participant_id,
                    interaction_id,
                ),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_record(
                row
            )

        finally:
            connection.close()

    def get_latest_for_operation(
        self,
        *,
        participant_id: str,
        operation_type: str,
    ) -> AIInteractionRecord | None:
        connection = connect(
            self._db_path
        )

        try:
            row = connection.execute(
                """
                SELECT
                    id,
                    participant_id,
                    attempt_id,
                    operation_type,
                    created_at,
                    prompt_version,
                    model_name,
                    structured_output_json,
                    status,
                    error_type
                FROM ai_interactions
                WHERE participant_id = ?
                  AND operation_type = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    participant_id,
                    operation_type,
                ),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_record(
                row
            )

        finally:
            connection.close()

    @staticmethod
    def _row_to_record(
        row: sqlite3.Row,
    ) -> AIInteractionRecord:
        return AIInteractionRecord(
            id=int(
                row["id"]
            ),
            participant_id=str(
                row[
                    "participant_id"
                ]
            ),
            attempt_id=(
                int(
                    row["attempt_id"]
                )
                if (
                    row["attempt_id"]
                    is not None
                )
                else None
            ),
            operation_type=str(
                row[
                    "operation_type"
                ]
            ),
            created_at=from_db_utc(
                row["created_at"]
            ),
            prompt_version=str(
                row[
                    "prompt_version"
                ]
            ),
            model_name=str(
                row[
                    "model_name"
                ]
            ),
            structured_output_json=(
                row[
                    "structured_output_json"
                ]
            ),
            status=str(
                row["status"]
            ),
            error_type=(
                row["error_type"]
            ),
        )