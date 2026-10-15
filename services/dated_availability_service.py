
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from domain.time_rules import ensure_aware
from repositories.availability_repository import (
    AvailabilityRepository,
    EventKind,
    DatedAvailabilityRecord,
)


class DatedAvailabilityService:
    def __init__(self, db_path: str | Path) -> None:
        self._repository = AvailabilityRepository(
            db_path
        )

    def list_events(
        self,
        *,
        participant_id: str,
        kind: EventKind,
    ) -> list[DatedAvailabilityRecord]:
        return self._repository.list_dated_events(
            participant_id=participant_id,
            kind=kind,
        )

    def save(
        self,
        *,
        participant_id: str,
        kind: EventKind,
        event_id: int | None,
        start_at: datetime,
        end_at: datetime,
        note: str,
        expected_version: int,
    ) -> int:
        ensure_aware(start_at)
        ensure_aware(end_at)

        if end_at <= start_at:
            raise ValueError(
                "終了日時は開始日時より"
                "後にしてください。"
            )

        # Streamlitの手入力でも5分単位を保証
        for dt in (start_at, end_at):
            if (
                dt.minute % 5 != 0
                or dt.second != 0
                or dt.microsecond != 0
            ):
                raise ValueError(
                    "時刻は5分単位で入力してください。"
                )

        normalized_note = note.strip()

        if len(normalized_note) > 500:
            raise ValueError(
                "メモは500文字以内にしてください。"
            )

        return self._repository.save_dated_event(
            participant_id=participant_id,
            kind=kind,
            event_id=event_id,
            start_at=start_at,
            end_at=end_at,
            note=normalized_note or None,
            expected_version=expected_version,
        )

    def delete(
        self,
        *,
        participant_id: str,
        kind: EventKind,
        event_id: int,
        expected_version: int,
    ) -> None:
        self._repository.delete_dated_event(
            participant_id=participant_id,
            kind=kind,
            event_id=event_id,
            expected_version=expected_version,
        )
