from __future__ import annotations

from pathlib import Path
import sqlite3

from db.connection import connect, transaction
from domain.models import (
    AvailableTime,
    BusyEvent,
    ExtraAvailableTime,
)
from domain.time_rules import (
    from_db_utc,
    to_db_utc,
)
from repositories.participant_repository import (
    ParticipantRepository,
)


class AvailabilityRepository:
    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(db_path)

    # =====================================================
    # Weekly AvailableTime
    # =====================================================

    def replace_available_times(
        self,
        participant_id: str,
        available_times: list[AvailableTime],
    ) -> None:
        with transaction(self._db_path) as connection:
            connection.execute(
                """
                DELETE FROM available_times
                WHERE participant_id = ?
                """,
                (participant_id,),
            )

            self.insert_available_times(
                connection,
                participant_id,
                available_times,
            )

            ParticipantRepository.increment_planning_data_version(
                connection,
                participant_id,
            )

    def insert_available_times(
        self,
        connection: sqlite3.Connection,
        participant_id: str,
        available_times: list[AvailableTime],
    ) -> None:
        for available_time in available_times:
            connection.execute(
                """
                INSERT INTO available_times (
                    participant_id,
                    weekday,
                    start_minute_of_day,
                    end_minute_of_day
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    participant_id,
                    available_time.weekday,
                    available_time.start_minute_of_day,
                    available_time.end_minute_of_day,
                ),
            )

    def list_available_times(
        self,
        participant_id: str,
    ) -> list[AvailableTime]:
        connection = connect(
            self._db_path
        )

        try:
            rows = connection.execute(
                """
                SELECT
                    weekday,
                    start_minute_of_day,
                    end_minute_of_day
                FROM available_times
                WHERE participant_id = ?
                ORDER BY
                    weekday,
                    start_minute_of_day,
                    end_minute_of_day
                """,
                (participant_id,),
            ).fetchall()

            return [
                AvailableTime(
                    weekday=int(
                        row["weekday"]
                    ),
                    start_minute_of_day=int(
                        row["start_minute_of_day"]
                    ),
                    end_minute_of_day=int(
                        row["end_minute_of_day"]
                    ),
                )
                for row in rows
            ]

        finally:
            connection.close()

    # =====================================================
    # BusyEvent
    # =====================================================

    def add_busy_event(
        self,
        participant_id: str,
        event: BusyEvent,
        note: str | None = None,
    ) -> int:
        with transaction(self._db_path) as connection:
            event_id = self.insert_busy_event(
                connection,
                participant_id,
                event,
                note=note,
            )

            ParticipantRepository.increment_planning_data_version(
                connection,
                participant_id,
            )

        return event_id

    def insert_busy_event(
        self,
        connection: sqlite3.Connection,
        participant_id: str,
        event: BusyEvent,
        note: str | None = None,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO busy_events (
                participant_id,
                start_at,
                end_at,
                note
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                participant_id,
                to_db_utc(event.start_at),
                to_db_utc(event.end_at),
                note,
            ),
        )

        event_id = cursor.lastrowid

        if event_id is None:
            raise RuntimeError(
                "failed to obtain busy_event id"
            )

        return int(event_id)

    def list_busy_events(
        self,
        participant_id: str,
    ) -> list[BusyEvent]:
        connection = connect(
            self._db_path
        )

        try:
            rows = connection.execute(
                """
                SELECT
                    start_at,
                    end_at
                FROM busy_events
                WHERE participant_id = ?
                ORDER BY start_at, id
                """,
                (participant_id,),
            ).fetchall()

            return [
                BusyEvent(
                    start_at=from_db_utc(
                        row["start_at"]
                    ),
                    end_at=from_db_utc(
                        row["end_at"]
                    ),
                )
                for row in rows
            ]

        finally:
            connection.close()

    # =====================================================
    # ExtraAvailableTime
    # =====================================================

    def add_extra_available_time(
        self,
        participant_id: str,
        event: ExtraAvailableTime,
        note: str | None = None,
    ) -> int:
        with transaction(self._db_path) as connection:
            event_id = (
                self.insert_extra_available_time(
                    connection,
                    participant_id,
                    event,
                    note=note,
                )
            )

            ParticipantRepository.increment_planning_data_version(
                connection,
                participant_id,
            )

        return event_id

    def insert_extra_available_time(
        self,
        connection: sqlite3.Connection,
        participant_id: str,
        event: ExtraAvailableTime,
        note: str | None = None,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO extra_available_times (
                participant_id,
                start_at,
                end_at,
                note
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                participant_id,
                to_db_utc(event.start_at),
                to_db_utc(event.end_at),
                note,
            ),
        )

        event_id = cursor.lastrowid

        if event_id is None:
            raise RuntimeError(
                "failed to obtain extra_available_time id"
            )

        return int(event_id)

    def list_extra_available_times(
        self,
        participant_id: str,
    ) -> list[ExtraAvailableTime]:
        connection = connect(
            self._db_path
        )

        try:
            rows = connection.execute(
                """
                SELECT
                    start_at,
                    end_at
                FROM extra_available_times
                WHERE participant_id = ?
                ORDER BY start_at, id
                """,
                (participant_id,),
            ).fetchall()

            return [
                ExtraAvailableTime(
                    start_at=from_db_utc(
                        row["start_at"]
                    ),
                    end_at=from_db_utc(
                        row["end_at"]
                    ),
                )
                for row in rows
            ]

        finally:
            connection.close()