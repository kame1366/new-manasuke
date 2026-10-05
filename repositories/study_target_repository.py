from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3

from db.connection import connect, transaction
from domain.enums import StudyTargetKind, UnitType
from domain.errors import DomainValidationError
from domain.models import (
    StudyTarget,
    StudyTargetRange,
)
from domain.time_rules import UTC, to_db_utc
from repositories.participant_repository import (
    ParticipantRepository,
)


class StudyTargetRepository:
    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(db_path)

    def create(
        self,
        target: StudyTarget,
    ) -> int:
        """
        StudyTargetを新規作成する。

        Source Data変更なので、
        planning_data_versionも同一transaction内で更新する。
        """
        with transaction(self._db_path) as connection:
            study_target_id = self.insert(
                connection,
                target.participant_id,
                target,
            )

            ParticipantRepository.increment_planning_data_version(
                connection,
                target.participant_id,
            )

        return study_target_id

    def insert(
        self,
        connection: sqlite3.Connection,
        participant_id: str,
        target: StudyTarget,
    ) -> int:
        """
        既存transaction内でStudyTargetをINSERTする。

        import_participant等から利用するため、
        ここではcommitやplanning_data_version更新を行わない。
        """
        if target.participant_id != participant_id:
            raise DomainValidationError(
                "StudyTarget participant_id does not match "
                "the repository operation participant_id"
            )

        now_text = to_db_utc(
            datetime.now(UTC)
        )

        cursor = connection.execute(
            """
            INSERT INTO study_targets (
                participant_id,
                kind,
                title,
                unit_type,
                next_position,
                estimated_minutes_per_unit,
                note,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                participant_id,
                target.kind.value,
                target.title,
                (
                    target.unit_type.value
                    if target.unit_type is not None
                    else None
                ),
                target.next_position,
                target.estimated_minutes_per_unit,
                target.note,
                now_text,
                now_text,
            ),
        )

        study_target_id = cursor.lastrowid

        if study_target_id is None:
            raise RuntimeError(
                "failed to obtain study_target_id"
            )

        sorted_ranges = sorted(
            target.ranges,
            key=lambda target_range: target_range.sequence_no,
        )

        for target_range in sorted_ranges:
            connection.execute(
                """
                INSERT INTO study_target_ranges (
                    study_target_id,
                    sequence_no,
                    start_position,
                    end_position
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    study_target_id,
                    target_range.sequence_no,
                    target_range.start_position,
                    target_range.end_position,
                ),
            )

        return int(study_target_id)

    def get_by_id(
        self,
        participant_id: str,
        study_target_id: int,
    ) -> StudyTarget | None:
        connection = connect(self._db_path)

        try:
            row = connection.execute(
                """
                SELECT
                    id,
                    participant_id,
                    kind,
                    title,
                    unit_type,
                    next_position,
                    estimated_minutes_per_unit,
                    note
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
                return None

            ranges = self._load_ranges(
                connection,
                study_target_id,
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
    ) -> list[StudyTarget]:
        connection = connect(self._db_path)

        try:
            rows = connection.execute(
                """
                SELECT
                    id,
                    participant_id,
                    kind,
                    title,
                    unit_type,
                    next_position,
                    estimated_minutes_per_unit,
                    note
                FROM study_targets
                WHERE participant_id = ?
                ORDER BY id
                """,
                (participant_id,),
            ).fetchall()

            results: list[StudyTarget] = []

            for row in rows:
                study_target_id = int(row["id"])

                ranges = self._load_ranges(
                    connection,
                    study_target_id,
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
        study_target_id: int,
    ) -> list[StudyTargetRange]:
        rows = connection.execute(
            """
            SELECT
                sequence_no,
                start_position,
                end_position
            FROM study_target_ranges
            WHERE study_target_id = ?
            ORDER BY sequence_no
            """,
            (study_target_id,),
        ).fetchall()

        return [
            StudyTargetRange(
                sequence_no=int(row["sequence_no"]),
                start_position=int(row["start_position"]),
                end_position=int(row["end_position"]),
            )
            for row in rows
        ]

    @staticmethod
    def _row_to_model(
        row: sqlite3.Row,
        ranges: list[StudyTargetRange],
    ) -> StudyTarget:
        kind = StudyTargetKind(
            row["kind"]
        )

        unit_type = (
            UnitType(row["unit_type"])
            if row["unit_type"] is not None
            else None
        )

        return StudyTarget(
            id=int(row["id"]),
            participant_id=str(row["participant_id"]),
            kind=kind,
            title=str(row["title"]),
            unit_type=unit_type,
            next_position=(
                int(row["next_position"])
                if row["next_position"] is not None
                else None
            ),
            estimated_minutes_per_unit=(
                float(row["estimated_minutes_per_unit"])
                if row["estimated_minutes_per_unit"]
                is not None
                else None
            ),
            note=row["note"],
            ranges=ranges,
        )