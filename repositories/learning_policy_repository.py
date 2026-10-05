from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3

from db.connection import connect, transaction
from domain.enums import Importance
from domain.errors import DomainValidationError
from domain.models import LearningPolicy
from domain.time_rules import UTC, to_db_utc
from repositories.participant_repository import (
    ParticipantRepository,
)


class LearningPolicyRepository:
    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(db_path)

    def create(
        self,
        participant_id: str,
        policy: LearningPolicy,
    ) -> None:
        with transaction(self._db_path) as connection:
            self.insert(
                connection,
                participant_id,
                policy,
            )

            ParticipantRepository.increment_planning_data_version(
                connection,
                participant_id,
            )

    def insert(
        self,
        connection: sqlite3.Connection,
        participant_id: str,
        policy: LearningPolicy,
    ) -> None:
        self._ensure_target_belongs_to_participant(
            connection,
            participant_id,
            policy.study_target_id,
        )

        now_text = to_db_utc(
            datetime.now(UTC)
        )

        connection.execute(
            """
            INSERT INTO learning_policies (
                participant_id,
                study_target_id,
                purpose,
                policy_priority,
                normal_sessions_per_week,
                normal_minutes,
                minimum_sessions_per_week,
                minimum_minutes,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                participant_id,
                policy.study_target_id,
                policy.purpose,
                policy.policy_priority.value,
                policy.normal_sessions_per_week,
                policy.normal_minutes,
                policy.minimum_sessions_per_week,
                policy.minimum_minutes,
                now_text,
                now_text,
            ),
        )

    def update(
        self,
        participant_id: str,
        policy: LearningPolicy,
    ) -> None:
        with transaction(self._db_path) as connection:
            self._ensure_target_belongs_to_participant(
                connection,
                participant_id,
                policy.study_target_id,
            )

            cursor = connection.execute(
                """
                UPDATE learning_policies
                SET
                    purpose = ?,
                    policy_priority = ?,
                    normal_sessions_per_week = ?,
                    normal_minutes = ?,
                    minimum_sessions_per_week = ?,
                    minimum_minutes = ?,
                    updated_at = ?
                WHERE participant_id = ?
                  AND study_target_id = ?
                """,
                (
                    policy.purpose,
                    policy.policy_priority.value,
                    policy.normal_sessions_per_week,
                    policy.normal_minutes,
                    policy.minimum_sessions_per_week,
                    policy.minimum_minutes,
                    to_db_utc(
                        datetime.now(UTC)
                    ),
                    participant_id,
                    policy.study_target_id,
                ),
            )

            if cursor.rowcount != 1:
                raise DomainValidationError(
                    "LearningPolicy not found"
                )

            ParticipantRepository.increment_planning_data_version(
                connection,
                participant_id,
            )

    def get_by_study_target(
        self,
        participant_id: str,
        study_target_id: int,
    ) -> LearningPolicy | None:
        connection = connect(
            self._db_path
        )

        try:
            row = connection.execute(
                """
                SELECT
                    study_target_id,
                    purpose,
                    policy_priority,
                    normal_sessions_per_week,
                    normal_minutes,
                    minimum_sessions_per_week,
                    minimum_minutes
                FROM learning_policies
                WHERE participant_id = ?
                  AND study_target_id = ?
                """,
                (
                    participant_id,
                    study_target_id,
                ),
            ).fetchone()

            if row is None:
                return None

            return self._row_to_model(
                row
            )

        finally:
            connection.close()

    def list_by_participant(
        self,
        participant_id: str,
    ) -> list[LearningPolicy]:
        connection = connect(
            self._db_path
        )

        try:
            rows = connection.execute(
                """
                SELECT
                    study_target_id,
                    purpose,
                    policy_priority,
                    normal_sessions_per_week,
                    normal_minutes,
                    minimum_sessions_per_week,
                    minimum_minutes
                FROM learning_policies
                WHERE participant_id = ?
                ORDER BY study_target_id
                """,
                (participant_id,),
            ).fetchall()

            return [
                self._row_to_model(row)
                for row in rows
            ]

        finally:
            connection.close()

    @staticmethod
    def _ensure_target_belongs_to_participant(
        connection: sqlite3.Connection,
        participant_id: str,
        study_target_id: int,
    ) -> None:
        row = connection.execute(
            """
            SELECT 1
            FROM study_targets
            WHERE participant_id = ?
              AND id = ?
            """,
            (
                participant_id,
                study_target_id,
            ),
        ).fetchone()

        if row is None:
            raise DomainValidationError(
                "StudyTarget does not belong "
                "to participant"
            )

    @staticmethod
    def _row_to_model(
        row: sqlite3.Row,
    ) -> LearningPolicy:
        return LearningPolicy(
            study_target_id=int(
                row["study_target_id"]
            ),
            purpose=str(
                row["purpose"]
            ),
            policy_priority=Importance(
                row["policy_priority"]
            ),
            normal_sessions_per_week=int(
                row["normal_sessions_per_week"]
            ),
            normal_minutes=int(
                row["normal_minutes"]
            ),
            minimum_sessions_per_week=int(
                row["minimum_sessions_per_week"]
            ),
            minimum_minutes=int(
                row["minimum_minutes"]
            ),
        )