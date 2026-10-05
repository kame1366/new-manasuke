from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3

from db.connection import connect, transaction
from domain.errors import DomainValidationError
from domain.time_rules import to_db_utc


class ParticipantRepository:
    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(db_path)

    def create(
        self,
        participant_id: str,
        created_at: datetime,
    ) -> None:
        with transaction(
            self._db_path
        ) as connection:
            self.insert(
                connection,
                participant_id,
                created_at,
            )

    def insert(
        self,
        connection: sqlite3.Connection,
        participant_id: str,
        created_at: datetime,
    ) -> None:
        normalized_id = participant_id.strip()

        if not normalized_id:
            raise DomainValidationError(
                "participant_id must not be empty"
            )

        connection.execute(
            """
            INSERT INTO participants (
                id,
                planning_data_version,
                created_at
            )
            VALUES (?, 0, ?)
            """,
            (
                normalized_id,
                to_db_utc(created_at),
            ),
        )

    def exists(
        self,
        participant_id: str,
    ) -> bool:
        connection = connect(
            self._db_path
        )

        try:
            row = connection.execute(
                """
                SELECT 1
                FROM participants
                WHERE id = ?
                """,
                (
                    participant_id,
                ),
            ).fetchone()

            return row is not None

        finally:
            connection.close()

    def get_planning_data_version(
        self,
        participant_id: str,
    ) -> int | None:
        connection = connect(
            self._db_path
        )

        try:
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
                return None

            return int(
                row["planning_data_version"]
            )

        finally:
            connection.close()

    @staticmethod
    def increment_planning_data_version(
        connection: sqlite3.Connection,
        participant_id: str,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE participants
            SET planning_data_version =
                planning_data_version + 1
            WHERE id = ?
            """,
            (
                participant_id,
            ),
        )

        if cursor.rowcount != 1:
            raise DomainValidationError(
                f"participant not found: {participant_id}"
            )