from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3

from db.connection import connect, transaction
from domain.enums import (
    GoalType,
    Importance,
)
from domain.errors import DomainValidationError
from domain.models import (
    Goal,
    GoalRange,
)
from domain.time_rules import (
    UTC,
    from_db_utc,
    to_db_utc,
)
from repositories.participant_repository import (
    ParticipantRepository,
)


class GoalRepository:
    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(db_path)

    def create(
        self,
        goal: Goal,
    ) -> int:
        with transaction(self._db_path) as connection:
            goal_id = self.insert(
                connection,
                goal.participant_id,
                goal,
            )

            ParticipantRepository.increment_planning_data_version(
                connection,
                goal.participant_id,
            )

        return goal_id

    def insert(
        self,
        connection: sqlite3.Connection,
        participant_id: str,
        goal: Goal,
    ) -> int:
        if goal.participant_id != participant_id:
            raise DomainValidationError(
                "Goal participant_id does not match "
                "the repository operation participant_id"
            )

        target_exists = connection.execute(
            """
            SELECT 1
            FROM study_targets
            WHERE participant_id = ?
              AND id = ?
            """,
            (
                participant_id,
                goal.study_target_id,
            ),
        ).fetchone()

        if target_exists is None:
            raise DomainValidationError(
                "Goal StudyTarget does not belong "
                "to participant"
            )

        now_text = to_db_utc(
            datetime.now(UTC)
        )

        cursor = connection.execute(
            """
            INSERT INTO goals (
                participant_id,
                study_target_id,
                goal_type,
                title,
                deadline_at,
                importance,
                target_minutes,
                note,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                participant_id,
                goal.study_target_id,
                goal.goal_type.value,
                goal.title,
                to_db_utc(goal.deadline_at),
                goal.importance.value,
                goal.target_minutes,
                goal.note,
                now_text,
                now_text,
            ),
        )

        goal_id = cursor.lastrowid

        if goal_id is None:
            raise RuntimeError(
                "failed to obtain goal_id"
            )

        for goal_range in goal.ranges:
            connection.execute(
                """
                INSERT INTO goal_ranges (
                    goal_id,
                    start_position,
                    end_position
                )
                VALUES (?, ?, ?)
                """,
                (
                    goal_id,
                    goal_range.start_position,
                    goal_range.end_position,
                ),
            )

        return int(goal_id)

    def get_by_id(
        self,
        participant_id: str,
        goal_id: int,
    ) -> Goal | None:
        connection = connect(
            self._db_path
        )

        try:
            row = connection.execute(
                """
                SELECT
                    id,
                    participant_id,
                    study_target_id,
                    goal_type,
                    title,
                    deadline_at,
                    importance,
                    target_minutes,
                    note
                FROM goals
                WHERE participant_id = ?
                  AND id = ?
                """,
                (
                    participant_id,
                    goal_id,
                ),
            ).fetchone()

            if row is None:
                return None

            ranges = self._load_ranges(
                connection,
                goal_id,
            )

            return self._row_to_model(
                row,
                ranges,
            )

        finally:
            connection.close()

    def list_by_participant(
        self,
        participant_id: str,
    ) -> list[Goal]:
        connection = connect(
            self._db_path
        )

        try:
            rows = connection.execute(
                """
                SELECT
                    id,
                    participant_id,
                    study_target_id,
                    goal_type,
                    title,
                    deadline_at,
                    importance,
                    target_minutes,
                    note
                FROM goals
                WHERE participant_id = ?
                ORDER BY deadline_at, id
                """,
                (participant_id,),
            ).fetchall()

            results: list[Goal] = []

            for row in rows:
                goal_id = int(
                    row["id"]
                )

                ranges = self._load_ranges(
                    connection,
                    goal_id,
                )

                results.append(
                    self._row_to_model(
                        row,
                        ranges,
                    )
                )

            return results

        finally:
            connection.close()

    @staticmethod
    def _load_ranges(
        connection: sqlite3.Connection,
        goal_id: int,
    ) -> list[GoalRange]:
        rows = connection.execute(
            """
            SELECT
                start_position,
                end_position
            FROM goal_ranges
            WHERE goal_id = ?
            ORDER BY id
            """,
            (goal_id,),
        ).fetchall()

        return [
            GoalRange(
                start_position=int(
                    row["start_position"]
                ),
                end_position=int(
                    row["end_position"]
                ),
            )
            for row in rows
        ]

    @staticmethod
    def _row_to_model(
        row: sqlite3.Row,
        ranges: list[GoalRange],
    ) -> Goal:
        return Goal(
            id=int(row["id"]),
            participant_id=str(
                row["participant_id"]
            ),
            study_target_id=int(
                row["study_target_id"]
            ),
            goal_type=GoalType(
                row["goal_type"]
            ),
            title=str(
                row["title"]
            ),
            deadline_at=from_db_utc(
                row["deadline_at"]
            ),
            importance=Importance(
                row["importance"]
            ),
            target_minutes=(
                int(row["target_minutes"])
                if row["target_minutes"]
                is not None
                else None
            ),
            note=row["note"],
            ranges=ranges,
        )