from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ai.errors import (
    PlanningDataChangedError,
)
from db.connection import (
    connect,
    transaction,
)
from domain.enums import (
    AttemptStage,
    AttemptStatus,
    PlanOperationType,
)
from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    PlanGenerationAttempt,
)
from domain.time_rules import (
    from_db_utc,
    to_db_utc,
)
from planning.attempt_errors import (
    AttemptAlreadyRunningError,
    AttemptNotActiveError,
    AttemptStageError,
)


ERROR_ATTEMPT_STALE_ABORTED = (
    "ATTEMPT_STALE_ABORTED"
)

ERROR_PLANNING_DATA_CHANGED = (
    "PLANNING_DATA_CHANGED"
)


class PlanGenerationAttemptRepository:
    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(
            db_path
        )

    def start(
        self,
        *,
        participant_id: str,
        operation_type: PlanOperationType,
        now: datetime,
        stale_after: timedelta,
    ) -> PlanGenerationAttempt:
        """
        participant単位で新しいPlan生成Attemptを開始する。

        同participantにIN_PROGRESSがある場合:

        - staleならABANDONEDにして新Attempt開始
        - staleでなければ拒否

        source_planning_data_versionは
        このTransaction内で固定する。
        """
        if stale_after.total_seconds() <= 0:
            raise DomainValidationError(
                "stale_after must be positive"
            )

        normalized_id = (
            participant_id.strip()
        )

        if not normalized_id:
            raise DomainValidationError(
                "participant_id must not be empty"
            )

        with transaction(
            self._db_path
        ) as connection:
            participant_row = (
                connection.execute(
                    """
                    SELECT planning_data_version
                    FROM participants
                    WHERE id = ?
                    """,
                    (
                        normalized_id,
                    ),
                ).fetchone()
            )

            if participant_row is None:
                raise DomainValidationError(
                    "participant not found: "
                    f"{normalized_id}"
                )

            current_version = int(
                participant_row[
                    "planning_data_version"
                ]
            )

            existing = connection.execute(
                """
                SELECT
                    id,
                    updated_at
                FROM plan_generation_attempts
                WHERE participant_id = ?
                  AND status = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    normalized_id,
                    AttemptStatus
                    .IN_PROGRESS
                    .value,
                ),
            ).fetchone()

            if existing is not None:
                existing_updated_at = (
                    from_db_utc(
                        existing[
                            "updated_at"
                        ]
                    )
                )

                age = (
                    now.astimezone(
                        existing_updated_at.tzinfo
                    )
                    - existing_updated_at
                )

                if age > stale_after:
                    stale_attempt_id = int(
                        existing["id"]
                    )

                    connection.execute(
                        """
                        UPDATE plan_generation_attempts
                        SET
                            status = ?,
                            updated_at = ?,
                            completed_at = ?,
                            error_type = ?
                        WHERE participant_id = ?
                          AND id = ?
                          AND status = ?
                        """,
                        (
                            AttemptStatus
                            .ABANDONED
                            .value,
                            to_db_utc(
                                now
                            ),
                            to_db_utc(
                                now
                            ),
                            (
                                ERROR_ATTEMPT_STALE_ABORTED
                            ),
                            normalized_id,
                            stale_attempt_id,
                            AttemptStatus
                            .IN_PROGRESS
                            .value,
                        ),
                    )

                    # stale AI callが後から戻ってきても
                    # RUNNING監査レコードを残さない。
                    connection.execute(
                        """
                        UPDATE ai_interactions
                        SET
                            status = 'FAILED',
                            error_type = ?
                        WHERE participant_id = ?
                          AND attempt_id = ?
                          AND status = 'RUNNING'
                        """,
                        (
                            ERROR_ATTEMPT_STALE_ABORTED,
                            normalized_id,
                            stale_attempt_id,
                        ),
                    )

                else:
                    raise (
                        AttemptAlreadyRunningError(
                            "plan generation is "
                            "already running"
                        )
                    )

            try:
                cursor = connection.execute(
                    """
                    INSERT INTO plan_generation_attempts (
                        participant_id,
                        operation_type,
                        source_planning_data_version,
                        status,
                        stage,
                        started_at,
                        updated_at,
                        completed_at,
                        error_type,
                        resulting_plan_id
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?,
                        NULL, NULL, NULL
                    )
                    """,
                    (
                        normalized_id,
                        operation_type.value,
                        current_version,
                        AttemptStatus
                        .IN_PROGRESS
                        .value,
                        AttemptStage
                        .FEASIBILITY
                        .value,
                        to_db_utc(
                            now
                        ),
                        to_db_utc(
                            now
                        ),
                    ),
                )

            except sqlite3.IntegrityError as exc:
                # partial UNIQUE index競合も
                # 「すでに生成中」として扱う。
                raise (
                    AttemptAlreadyRunningError(
                        "plan generation is "
                        "already running"
                    )
                ) from exc

            attempt_id = (
                cursor.lastrowid
            )

            if attempt_id is None:
                raise RuntimeError(
                    "failed to create "
                    "PlanGenerationAttempt"
                )

        result = self.get_by_id(
            normalized_id,
            int(
                attempt_id
            ),
        )

        if result is None:
            raise RuntimeError(
                "created Attempt "
                "could not be loaded"
            )

        return result

    def get_by_id(
        self,
        participant_id: str,
        attempt_id: int,
    ) -> PlanGenerationAttempt | None:
        connection = connect(
            self._db_path
        )

        try:
            row = connection.execute(
                """
                SELECT
                    id,
                    participant_id,
                    operation_type,
                    source_planning_data_version,
                    status,
                    stage,
                    started_at,
                    updated_at,
                    completed_at,
                    error_type,
                    resulting_plan_id
                FROM plan_generation_attempts
                WHERE participant_id = ?
                  AND id = ?
                """,
                (
                    participant_id,
                    attempt_id,
                ),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_model(
                row
            )

        finally:
            connection.close()

    def get_current_in_progress(
        self,
        participant_id: str,
    ) -> PlanGenerationAttempt | None:
        connection = connect(
            self._db_path
        )

        try:
            row = connection.execute(
                """
                SELECT
                    id,
                    participant_id,
                    operation_type,
                    source_planning_data_version,
                    status,
                    stage,
                    started_at,
                    updated_at,
                    completed_at,
                    error_type,
                    resulting_plan_id
                FROM plan_generation_attempts
                WHERE participant_id = ?
                  AND status = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    participant_id,
                    AttemptStatus
                    .IN_PROGRESS
                    .value,
                ),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_model(
                row
            )

        finally:
            connection.close()

    def mark_failed(
        self,
        *,
        participant_id: str,
        attempt_id: int,
        error_type: str,
        now: datetime,
    ) -> None:
        with transaction(
            self._db_path
        ) as connection:
            cursor = connection.execute(
                """
                UPDATE plan_generation_attempts
                SET
                    status = ?,
                    updated_at = ?,
                    completed_at = ?,
                    error_type = ?
                WHERE participant_id = ?
                  AND id = ?
                  AND status = ?
                """,
                (
                    AttemptStatus
                    .FAILED
                    .value,
                    to_db_utc(
                        now
                    ),
                    to_db_utc(
                        now
                    ),
                    error_type,
                    participant_id,
                    attempt_id,
                    AttemptStatus
                    .IN_PROGRESS
                    .value,
                ),
            )

            if cursor.rowcount != 1:
                raise AttemptNotActiveError(
                    "Attempt is not IN_PROGRESS"
                )

    @staticmethod
    def assert_in_progress_in_transaction(
        connection: sqlite3.Connection,
        *,
        participant_id: str,
        attempt_id: int,
        expected_stage: (
            AttemptStage | None
        ) = None,
    ) -> PlanGenerationAttempt:
        row = connection.execute(
            """
            SELECT
                id,
                participant_id,
                operation_type,
                source_planning_data_version,
                status,
                stage,
                started_at,
                updated_at,
                completed_at,
                error_type,
                resulting_plan_id
            FROM plan_generation_attempts
            WHERE participant_id = ?
              AND id = ?
            """,
            (
                participant_id,
                attempt_id,
            ),
        ).fetchone()

        if row is None:
            raise DomainValidationError(
                "PlanGenerationAttempt not found"
            )

        attempt = (
            PlanGenerationAttemptRepository
            ._row_to_model(
                row
            )
        )

        if (
            attempt.status
            != AttemptStatus.IN_PROGRESS
        ):
            raise AttemptNotActiveError(
                "Attempt is no longer "
                "IN_PROGRESS"
            )

        if (
            expected_stage is not None
            and attempt.stage
            != expected_stage
        ):
            raise AttemptStageError(
                "Attempt stage mismatch: "
                f"expected={expected_stage.value}, "
                f"actual={attempt.stage.value}"
            )

        return attempt

    @staticmethod
    def assert_source_version_in_transaction(
        connection: sqlite3.Connection,
        *,
        participant_id: str,
        attempt: PlanGenerationAttempt,
    ) -> None:
        row = connection.execute(
            """
            SELECT planning_data_version
            FROM participants
            WHERE id = ?
            """,
            (
                participant_id,
            ),
        ).fetchone()

        if row is None:
            raise DomainValidationError(
                "participant not found"
            )

        current_version = int(
            row[
                "planning_data_version"
            ]
        )

        if (
            current_version
            != attempt
            .source_planning_data_version
        ):
            raise PlanningDataChangedError(
                "planning_data_version changed "
                "during Plan generation"
            )

    @staticmethod
    def advance_stage_in_transaction(
        connection: sqlite3.Connection,
        *,
        participant_id: str,
        attempt_id: int,
        next_stage: AttemptStage,
        now: datetime,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE plan_generation_attempts
            SET
                stage = ?,
                updated_at = ?
            WHERE participant_id = ?
              AND id = ?
              AND status = ?
            """,
            (
                next_stage.value,
                to_db_utc(
                    now
                ),
                participant_id,
                attempt_id,
                AttemptStatus
                .IN_PROGRESS
                .value,
            ),
        )

        if cursor.rowcount != 1:
            raise AttemptNotActiveError(
                "Attempt is no longer "
                "IN_PROGRESS"
            )

    @staticmethod
    def _row_to_model(
        row: sqlite3.Row,
    ) -> PlanGenerationAttempt:
        return PlanGenerationAttempt(
            id=int(
                row["id"]
            ),
            participant_id=str(
                row[
                    "participant_id"
                ]
            ),
            operation_type=(
                PlanOperationType(
                    row[
                        "operation_type"
                    ]
                )
            ),
            source_planning_data_version=int(
                row[
                    "source_planning_data_version"
                ]
            ),
            status=AttemptStatus(
                row["status"]
            ),
            stage=AttemptStage(
                row["stage"]
            ),
            started_at=from_db_utc(
                row["started_at"]
            ),
            updated_at=from_db_utc(
                row["updated_at"]
            ),
            completed_at=(
                from_db_utc(
                    row[
                        "completed_at"
                    ]
                )
                if (
                    row[
                        "completed_at"
                    ]
                    is not None
                )
                else None
            ),
            error_type=(
                row["error_type"]
            ),
            resulting_plan_id=(
                int(
                    row[
                        "resulting_plan_id"
                    ]
                )
                if (
                    row[
                        "resulting_plan_id"
                    ]
                    is not None
                )
                else None
            ),
        )