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
        free_slots: Sequence[FreeSlot],
        used_study_days: frozenset[date] = frozenset(),
        additional_not_before: datetime | None = None,
        prefer_new_study_day: bool = True,
    ) -> PlacementOutcome:
        """
        WorkChunkを最も早い有効FreeSlotへ配置する。

        prefer_new_study_day=Trueの場合も、
        distributed practiceはSoft preference。

        まず未使用study dayを優先し、
        そこに配置できなければ
        既使用study dayへfallbackする。
        """

        effective_not_before = (
            chunk.not_before
        )

        if (
            additional_not_before
            is not None
            and (
                effective_not_before is None
                or additional_not_before
                > effective_not_before
            )
        ):
            effective_not_before = (
                additional_not_before
            )

        all_candidates: list[
            tuple[
                FreeSlot,
                datetime,
                datetime,
            ]
        ] = []

        preferred_candidates: list[
            tuple[
                FreeSlot,
                datetime,
                datetime,
            ]
        ] = []

        for slot in sorted(
            free_slots,
            key=lambda value: (
                value.start_at,
                value.end_at,
            ),
        ):
            start_at = slot.start_at

            if (
                effective_not_before
                is not None
                and start_at
                < effective_not_before
            ):
                start_at = (
                    effective_not_before
                )

            start_at = (
                ceil_to_5_minutes(
                    start_at
                )
            )

            end_at = (
                start_at
                + timedelta(
                    minutes=(
                        chunk
                        .scheduled_duration_minutes
                    )
                )
            )

            if end_at > slot.end_at:
                continue

            if (
                chunk.must_finish_before
                is not None
                and end_at
                > chunk.must_finish_before
            ):
                continue

            local_start = (
                to_jst(
                    start_at
                )
            )

            local_end = (
                to_jst(
                    end_at
                )
            )

            if (
                local_start.date()
                != local_end.date()
            ):
                continue

            candidate = (
                slot,
                start_at,
                end_at,
            )

            all_candidates.append(
                candidate
            )

            study_day = (
                local_start.date()
            )

            if (
                study_day
                not in used_study_days
            ):
                preferred_candidates.append(
                    candidate
                )

        if (
            prefer_new_study_day
            and preferred_candidates
        ):
            candidates = (
                preferred_candidates
            )

        else:
            candidates = (
                all_candidates
            )

        if not candidates:
            return PlacementOutcome(
                placement=None,
                remaining_slots=tuple(
                    free_slots
                ),
            )

        slot, start_at, end_at = min(
            candidates,
            key=lambda value: (
                value[1],
                value[2],
            ),
        )

        placement = ScheduledChunk(
            chunk=chunk,
            start_at=start_at,
            end_at=end_at,
        )

        remaining_slots = (
            self._subtract_placement(
                free_slots=(
                    free_slots
                ),
                used_slot=slot,
                placement_start=(
                    start_at
                ),
                placement_end=(
                    end_at
                ),
            )
        )

        return PlacementOutcome(
            placement=placement,
            remaining_slots=(
                remaining_slots
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

    def _subtract_placement(
        self,
        *,
        free_slots: Sequence[
            FreeSlot
        ],
        used_slot: FreeSlot,
        placement_start: datetime,
        placement_end: datetime,
    ) -> tuple[
        FreeSlot,
        ...,
    ]:
        result: list[
            FreeSlot
        ] = []

        for slot in free_slots:
            if slot != used_slot:
                result.append(
                    slot
                )
                continue

            # 左側の残り
            if (
                slot.start_at
                < placement_start
            ):
                left = FreeSlot(
                    start_at=(
                        slot.start_at
                    ),
                    end_at=(
                        placement_start
                    ),
                )

                if (
                    left.end_at
                    - left.start_at
                ) >= timedelta(
                    minutes=10
                ):
                    result.append(
                        left
                    )

            # 右側の残り
            if (
                placement_end
                < slot.end_at
            ):
                right = FreeSlot(
                    start_at=(
                        placement_end
                    ),
                    end_at=(
                        slot.end_at
                    ),
                )

                if (
                    right.end_at
                    - right.start_at
                ) >= timedelta(
                    minutes=10
                ):
                    result.append(
                        right
                    )

        result.sort(
            key=lambda value: (
                value.start_at,
                value.end_at,
            )
        )

        return tuple(
            result
        )