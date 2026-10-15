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

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


class AvailabilityConflictError(RuntimeError):
    """編集中に学習設定が変更された。"""
    pass


EventKind = Literal["busy", "extra"]


@dataclass(frozen=True, slots=True)
class DatedAvailabilityRecord:
    id: int
    start_at: datetime
    end_at: datetime
    note: str | None


class AvailabilityRecordNotFoundError(RuntimeError):
    pass

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
        if note is None:
            note = event.note

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
        if note is None:
            note = event.note

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
                    end_at,
                    note
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
                    note=row["note"],
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
        if note is None:
            note = event.note

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
        if note is None:
            note = event.note

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
                    end_at,
                    note
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
                    note=row["note"],
                )
                for row in rows
            ]

        finally:
            connection.close()

    def replace_available_times_if_version(
        self,
        *,
        participant_id: str,
        available_times: list[AvailableTime],
        expected_version: int,
    ) -> None:
        with transaction(self._db_path) as connection:

            # Versionを原子的に確認・更新する。
            cursor = connection.execute(
                """
                UPDATE participants
                SET planning_data_version =
                    planning_data_version + 1
                WHERE id = ?
                AND planning_data_version = ?
                """,
                (participant_id, expected_version),
            )

            if cursor.rowcount != 1:
                raise AvailabilityConflictError(
                    "設定が別の操作によって変更されました。"
                    "最新の設定を読み込み直してください。"
                )

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

    
    # =====================================================
    # Editable BusyEvent / ExtraAvailableTime
    # =====================================================

    @staticmethod
    def _event_table(kind: EventKind) -> str:
        tables = {
            "busy": "busy_events",
            "extra": "extra_available_times",
        }

        if kind not in tables:
            raise ValueError("Unknown availability kind")

        return tables[kind]

    @staticmethod
    def _bump_version_if_current(
        connection: sqlite3.Connection,
        participant_id: str,
        expected_version: int,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE participants
            SET planning_data_version =
                planning_data_version + 1
            WHERE id = ?
              AND planning_data_version = ?
            """,
            (participant_id, expected_version),
        )

        if cursor.rowcount != 1:
            raise AvailabilityConflictError(
                "学習設定が別の操作で変更されました。"
                "最新の設定を読み込んでください。"
            )

    def list_dated_events(
        self,
        *,
        participant_id: str,
        kind: EventKind,
    ) -> list[DatedAvailabilityRecord]:
        table = self._event_table(kind)
        connection = connect(self._db_path)

        try:
            rows = connection.execute(
                f"""
                SELECT id, start_at, end_at, note
                FROM {table}
                WHERE participant_id = ?
                ORDER BY start_at, id
                """,
                (participant_id,),
            ).fetchall()

            return [
                DatedAvailabilityRecord(
                    id=int(row["id"]),
                    start_at=from_db_utc(row["start_at"]),
                    end_at=from_db_utc(row["end_at"]),
                    note=row["note"],
                )
                for row in rows
            ]
        finally:
            connection.close()

    def save_dated_event(
        self,
        *,
        participant_id: str,
        kind: EventKind,
        event_id: int | None,
        start_at: datetime,
        end_at: datetime,
        note: str | None,
        expected_version: int,
    ) -> int:
        table = self._event_table(kind)

        with transaction(self._db_path) as connection:
            self._bump_version_if_current(
                connection,
                participant_id,
                expected_version,
            )

            if event_id is None:
                cursor = connection.execute(
                    f"""
                    INSERT INTO {table} (
                        participant_id,
                        start_at,
                        end_at,
                        note
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        participant_id,
                        to_db_utc(start_at),
                        to_db_utc(end_at),
                        note,
                    ),
                )

                if cursor.lastrowid is None:
                    raise RuntimeError(
                        "Failed to insert availability event"
                    )

                return int(cursor.lastrowid)

            cursor = connection.execute(
                f"""
                UPDATE {table}
                SET start_at = ?,
                    end_at = ?,
                    note = ?
                WHERE id = ?
                  AND participant_id = ?
                """,
                (
                    to_db_utc(start_at),
                    to_db_utc(end_at),
                    note,
                    event_id,
                    participant_id,
                ),
            )

            if cursor.rowcount != 1:
                raise AvailabilityRecordNotFoundError(
                    "編集対象の予定が見つかりません。"
                )

            return event_id

    def delete_dated_event(
        self,
        *,
        participant_id: str,
        kind: EventKind,
        event_id: int,
        expected_version: int,
    ) -> None:
        table = self._event_table(kind)

        with transaction(self._db_path) as connection:
            self._bump_version_if_current(
                connection,
                participant_id,
                expected_version,
            )

            cursor = connection.execute(
                f"""
                DELETE FROM {table}
                WHERE id = ?
                  AND participant_id = ?
                """,
                (event_id, participant_id),
            )

            if cursor.rowcount != 1:
                raise AvailabilityRecordNotFoundError(
                    "削除対象の予定が見つかりません。"
                )
