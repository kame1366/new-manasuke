from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import (
    date,
    datetime,
    time,
    timedelta,
)

from domain.errors import (
    DomainValidationError,
)
from domain.models import (
    AvailableTime,
    BusyEvent,
    ExtraAvailableTime,
    PlanItem,
)
from domain.time_rules import (
    JST,
    ceil_to_5_minutes,
    ensure_aware,
    floor_to_5_minutes,
    split_at_midnight,
    to_jst,
)


MINIMUM_SLOT_MINUTES = 10


@dataclass(
    frozen=True,
    slots=True,
)
class FreeSlot:
    """
    Schedulerへ渡す利用可能時間。

    DBへは保存しない派生オブジェクト。
    """

    start_at: datetime
    end_at: datetime

    def __post_init__(
        self,
    ) -> None:
        ensure_aware(
            self.start_at
        )
        ensure_aware(
            self.end_at
        )

        if (
            self.start_at
            >= self.end_at
        ):
            raise DomainValidationError(
                "FreeSlot start_at must be "
                "earlier than end_at"
            )

    @property
    def duration_minutes(
        self,
    ) -> int:
        duration = (
            self.end_at
            - self.start_at
        )

        return int(
            duration.total_seconds()
            // 60
        )


Interval = tuple[
    datetime,
    datetime,
]


class FreeSlotBuilder:
    """
    Weekly AvailableTime、
    ExtraAvailableTime、
    BusyEvent、
    fixed PlanItemから
    FreeSlotを構築する。
    """

    def build(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        weekly_available_times: Sequence[
            AvailableTime
        ],
        extra_available_times: Sequence[
            ExtraAvailableTime
        ],
        busy_events: Sequence[
            BusyEvent
        ],
        fixed_plan_items: Sequence[
            PlanItem
        ],
    ) -> list[FreeSlot]:
        """
        FreeSlotを構築する。

        手順:
        1. Weekly AvailableTimeをdatetime展開
        2. ExtraAvailableTimeをunion
        3. overlap / touchingをmerge
        4. BusyEvent / fixed PlanItemをsubtract
        5. midnightでsplit
        6. start ceil5 / end floor5
        7. 10分未満drop
        """

        ensure_aware(
            window_start
        )
        ensure_aware(
            window_end
        )

        if (
            window_start
            >= window_end
        ):
            raise DomainValidationError(
                "window_start must be "
                "earlier than window_end"
            )

        window_start_jst = to_jst(
            window_start
        )
        window_end_jst = to_jst(
            window_end
        )

        weekly_intervals = (
            self._expand_weekly_available_times(
                window_start=window_start_jst,
                window_end=window_end_jst,
                weekly_available_times=(
                    weekly_available_times
                ),
            )
        )

        extra_intervals = (
            self._build_extra_intervals(
                window_start=window_start_jst,
                window_end=window_end_jst,
                extra_available_times=(
                    extra_available_times
                ),
            )
        )

        available_intervals = (
            self._merge_intervals(
                [
                    *weekly_intervals,
                    *extra_intervals,
                ]
            )
        )

        blocked_intervals = (
            self._build_blocked_intervals(
                window_start=window_start_jst,
                window_end=window_end_jst,
                busy_events=busy_events,
                fixed_plan_items=(
                    fixed_plan_items
                ),
            )
        )

        blocked_intervals = (
            self._merge_intervals(
                blocked_intervals
            )
        )

        remaining_intervals = (
            self._subtract_intervals(
                available_intervals,
                blocked_intervals,
            )
        )

        split_intervals: list[
            Interval
        ] = []

        for (
            start_at,
            end_at,
        ) in remaining_intervals:
            split_intervals.extend(
                split_at_midnight(
                    start_at,
                    end_at,
                )
            )

        aligned_slots: list[
            FreeSlot
        ] = []

        for (
            start_at,
            end_at,
        ) in split_intervals:
            aligned_start = (
                ceil_to_5_minutes(
                    start_at
                )
            )

            aligned_end = (
                floor_to_5_minutes(
                    end_at
                )
            )

            if (
                aligned_start
                >= aligned_end
            ):
                continue

            duration_minutes = int(
                (
                    aligned_end
                    - aligned_start
                ).total_seconds()
                // 60
            )

            if (
                duration_minutes
                < MINIMUM_SLOT_MINUTES
            ):
                continue

            aligned_slots.append(
                FreeSlot(
                    start_at=aligned_start,
                    end_at=aligned_end,
                )
            )

        aligned_slots.sort(
            key=lambda slot: (
                slot.start_at,
                slot.end_at,
            )
        )

        return aligned_slots

    @staticmethod
    def _expand_weekly_available_times(
        *,
        window_start: datetime,
        window_end: datetime,
        weekly_available_times: Sequence[
            AvailableTime
        ],
    ) -> list[Interval]:
        intervals: list[
            Interval
        ] = []

        current_date = (
            window_start.date()
        )

        while True:
            day_start = datetime.combine(
                current_date,
                time.min,
                tzinfo=JST,
            )

            if (
                day_start
                >= window_end
            ):
                break

            weekday = (
                current_date.weekday()
            )

            for available in (
                weekly_available_times
            ):
                if (
                    available.weekday
                    != weekday
                ):
                    continue

                start_at = (
                    day_start
                    + timedelta(
                        minutes=(
                            available
                            .start_minute_of_day
                        )
                    )
                )

                end_at = (
                    day_start
                    + timedelta(
                        minutes=(
                            available
                            .end_minute_of_day
                        )
                    )
                )

                clipped = (
                    FreeSlotBuilder
                    ._clip_interval(
                        start_at,
                        end_at,
                        window_start,
                        window_end,
                    )
                )

                if (
                    clipped is not None
                ):
                    intervals.append(
                        clipped
                    )

            current_date += timedelta(
                days=1
            )

        return intervals

    @staticmethod
    def _build_extra_intervals(
        *,
        window_start: datetime,
        window_end: datetime,
        extra_available_times: Sequence[
            ExtraAvailableTime
        ],
    ) -> list[Interval]:
        intervals: list[
            Interval
        ] = []

        for extra in (
            extra_available_times
        ):
            clipped = (
                FreeSlotBuilder
                ._clip_interval(
                    to_jst(
                        extra.start_at
                    ),
                    to_jst(
                        extra.end_at
                    ),
                    window_start,
                    window_end,
                )
            )

            if (
                clipped is not None
            ):
                intervals.append(
                    clipped
                )

        return intervals

    @staticmethod
    def _build_blocked_intervals(
        *,
        window_start: datetime,
        window_end: datetime,
        busy_events: Sequence[
            BusyEvent
        ],
        fixed_plan_items: Sequence[
            PlanItem
        ],
    ) -> list[Interval]:
        intervals: list[
            Interval
        ] = []

        for busy_event in (
            busy_events
        ):
            clipped = (
                FreeSlotBuilder
                ._clip_interval(
                    to_jst(
                        busy_event.start_at
                    ),
                    to_jst(
                        busy_event.end_at
                    ),
                    window_start,
                    window_end,
                )
            )

            if (
                clipped is not None
            ):
                intervals.append(
                    clipped
                )

        for plan_item in (
            fixed_plan_items
        ):
            if plan_item.is_cancelled:
                continue

            clipped = (
                FreeSlotBuilder
                ._clip_interval(
                    to_jst(
                        plan_item.start_at
                    ),
                    to_jst(
                        plan_item.end_at
                    ),
                    window_start,
                    window_end,
                )
            )

            if (
                clipped is not None
            ):
                intervals.append(
                    clipped
                )

        return intervals

    @staticmethod
    def _clip_interval(
        start_at: datetime,
        end_at: datetime,
        window_start: datetime,
        window_end: datetime,
    ) -> Interval | None:
        """
        intervalをwindow内へclipする。

        完全にwindow外ならNone。
        """

        if (
            end_at
            <= window_start
            or start_at
            >= window_end
        ):
            return None

        clipped_start = max(
            start_at,
            window_start,
        )

        clipped_end = min(
            end_at,
            window_end,
        )

        if (
            clipped_start
            >= clipped_end
        ):
            return None

        return (
            clipped_start,
            clipped_end,
        )

    @staticmethod
    def _merge_intervals(
        intervals: Sequence[
            Interval
        ],
    ) -> list[Interval]:
        """
        overlapまたはtouchingしているintervalをmergeする。

        例:
            18:00-19:00
            19:00-20:00

        ↓

            18:00-20:00
        """
        if not intervals:
            return []

        sorted_intervals = sorted(
            intervals,
            key=lambda interval: (
                interval[0],
                interval[1],
            ),
        )

        merged: list[
            Interval
        ] = [
            sorted_intervals[0]
        ]

        for (
            start_at,
            end_at,
        ) in sorted_intervals[1:]:
            (
                last_start,
                last_end,
            ) = merged[-1]

            if (
                start_at
                <= last_end
            ):
                merged[-1] = (
                    last_start,
                    max(
                        last_end,
                        end_at,
                    ),
                )

            else:
                merged.append(
                    (
                        start_at,
                        end_at,
                    )
                )

        return merged

    @staticmethod
    def _subtract_intervals(
        base_intervals: Sequence[
            Interval
        ],
        blocked_intervals: Sequence[
            Interval
        ],
    ) -> list[Interval]:
        """
        base intervalsからblocked intervalsを引く。
        """
        result: list[
            Interval
        ] = []

        for (
            base_start,
            base_end,
        ) in base_intervals:
            fragments: list[
                Interval
            ] = [
                (
                    base_start,
                    base_end,
                )
            ]

            for (
                block_start,
                block_end,
            ) in blocked_intervals:
                next_fragments: list[
                    Interval
                ] = []

                for (
                    fragment_start,
                    fragment_end,
                ) in fragments:
                    if (
                        block_end
                        <= fragment_start
                        or block_start
                        >= fragment_end
                    ):
                        next_fragments.append(
                            (
                                fragment_start,
                                fragment_end,
                            )
                        )
                        continue

                    if (
                        block_start
                        > fragment_start
                    ):
                        next_fragments.append(
                            (
                                fragment_start,
                                min(
                                    block_start,
                                    fragment_end,
                                ),
                            )
                        )

                    if (
                        block_end
                        < fragment_end
                    ):
                        next_fragments.append(
                            (
                                max(
                                    block_end,
                                    fragment_start,
                                ),
                                fragment_end,
                            )
                        )

                fragments = (
                    next_fragments
                )

                if not fragments:
                    break

            result.extend(
                fragments
            )

        result.sort(
            key=lambda interval: (
                interval[0],
                interval[1],
            )
        )

        return result