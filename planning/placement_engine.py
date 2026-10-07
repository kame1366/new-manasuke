from __future__ import annotations

from collections.abc import Set, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from domain.errors import DomainValidationError
from domain.time_rules import (
    JST,
    ceil_to_5_minutes,
    ensure_aware,
    to_jst,
)
from planning.free_slot_builder import FreeSlot
from planning.work_chunk_builder import WorkChunk


@dataclass(
    frozen=True,
    slots=True,
)
class ScheduledChunk:
    """
    WorkChunkの具体的なcalendar配置結果。
    """

    chunk: WorkChunk

    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        ensure_aware(
            self.start_at
        )
        ensure_aware(
            self.end_at
        )

        if self.start_at >= self.end_at:
            raise DomainValidationError(
                "ScheduledChunk start_at must "
                "be earlier than end_at"
            )

        duration = int(
            (
                self.end_at
                - self.start_at
            ).total_seconds()
            // 60
        )

        if (
            duration
            != self.chunk
            .scheduled_duration_minutes
        ):
            raise DomainValidationError(
                "ScheduledChunk duration does "
                "not match WorkChunk"
            )

        start_jst = to_jst(
            self.start_at
        )

        end_jst = to_jst(
            self.end_at
        )

        same_day = (
            start_jst.date()
            == end_jst.date()
        )

        ends_at_next_midnight = (
            end_jst.date()
            == start_jst.date()
            + timedelta(days=1)
            and end_jst.time()
            == time.min
        )

        if not (
            same_day
            or ends_at_next_midnight
        ):
            raise DomainValidationError(
                "ScheduledChunk must fit within "
                "one JST calendar day"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class PlacementOutcome:
    placement: ScheduledChunk | None

    remaining_slots: tuple[
        FreeSlot,
        ...,
    ]


class PlacementEngine:
    """
    1 WorkChunkをFreeSlotへ配置する決定論的engine。

    distributed practiceはSoft preferenceなので、
    未使用日を優先するが、
    無理なら同日複数sessionを許可する。
    """

    def place_chunk(
        self,
        *,
        chunk: WorkChunk,
        free_slots: Sequence[
            FreeSlot
        ],
        used_study_days: Set[
            date
        ] = frozenset(),
        additional_not_before: datetime
        | None = None,
        prefer_new_study_day: bool = True,
    ) -> PlacementOutcome:
        if additional_not_before is not None:
            ensure_aware(
                additional_not_before
            )

        candidates: list[
            tuple[
                bool,
                datetime,
                datetime,
                int,
            ]
        ] = []

        for index, slot in enumerate(
            free_slots
        ):
            candidate_start = (
                slot.start_at
            )

            boundaries = [
                boundary
                for boundary in (
                    chunk.not_before,
                    additional_not_before,
                )
                if boundary is not None
            ]

            if boundaries:
                lower_bound = max(
                    boundaries
                )

                if (
                    candidate_start
                    < lower_bound
                ):
                    candidate_start = (
                        ceil_to_5_minutes(
                            lower_bound
                        )
                    )

            if (
                candidate_start
                < slot.start_at
            ):
                candidate_start = (
                    slot.start_at
                )

            candidate_end = (
                candidate_start
                + timedelta(
                    minutes=(
                        chunk
                        .scheduled_duration_minutes
                    )
                )
            )

            if (
                candidate_end
                > slot.end_at
            ):
                continue

            if (
                chunk.must_finish_before
                is not None
                and candidate_end
                > chunk.must_finish_before
            ):
                continue

            study_day = to_jst(
                candidate_start
            ).date()

            already_used = (
                study_day
                in used_study_days
            )

            candidates.append(
                (
                    already_used,
                    candidate_start,
                    candidate_end,
                    index,
                )
            )

        if not candidates:
            return PlacementOutcome(
                placement=None,
                remaining_slots=tuple(
                    free_slots
                ),
            )

        if prefer_new_study_day:
            candidates.sort(
                key=lambda item: (
                    item[0],
                    item[1],
                    item[3],
                )
            )
        else:
            candidates.sort(
                key=lambda item: (
                    item[1],
                    item[3],
                )
            )

        (
            _already_used,
            start_at,
            end_at,
            slot_index,
        ) = candidates[0]

        placement = ScheduledChunk(
            chunk=chunk,
            start_at=start_at,
            end_at=end_at,
        )

        remaining = (
            self._consume_slot(
                free_slots=free_slots,
                slot_index=slot_index,
                start_at=start_at,
                end_at=end_at,
            )
        )

        return PlacementOutcome(
            placement=placement,
            remaining_slots=tuple(
                remaining
            ),
        )

    @staticmethod
    def _consume_slot(
        *,
        free_slots: Sequence[
            FreeSlot
        ],
        slot_index: int,
        start_at: datetime,
        end_at: datetime,
    ) -> list[FreeSlot]:
        result: list[
            FreeSlot
        ] = []

        for index, slot in enumerate(
            free_slots
        ):
            if index != slot_index:
                result.append(
                    slot
                )
                continue

            if (
                slot.start_at
                < start_at
            ):
                left_minutes = int(
                    (
                        start_at
                        - slot.start_at
                    ).total_seconds()
                    // 60
                )

                if left_minutes >= 10:
                    result.append(
                        FreeSlot(
                            start_at=(
                                slot.start_at
                            ),
                            end_at=start_at,
                        )
                    )

            if (
                end_at
                < slot.end_at
            ):
                right_minutes = int(
                    (
                        slot.end_at
                        - end_at
                    ).total_seconds()
                    // 60
                )

                if right_minutes >= 10:
                    result.append(
                        FreeSlot(
                            start_at=end_at,
                            end_at=(
                                slot.end_at
                            ),
                        )
                    )

        result.sort(
            key=lambda slot: (
                slot.start_at,
                slot.end_at,
            )
        )

        return result