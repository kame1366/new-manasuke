from datetime import datetime

import pytest

from domain.enums import (
    PlanItemOrigin,
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
    UTC,
)
from planning.free_slot_builder import (
    FreeSlotBuilder,
)


def jst(
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(
        2026,
        10,
        day,
        hour,
        minute,
        tzinfo=JST,
    )


def build(
    *,
    window_start: datetime,
    window_end: datetime,
    weekly_available_times=None,
    extra_available_times=None,
    busy_events=None,
    fixed_plan_items=None,
):
    builder = FreeSlotBuilder()

    return builder.build(
        window_start=window_start,
        window_end=window_end,
        weekly_available_times=(
            weekly_available_times
            or []
        ),
        extra_available_times=(
            extra_available_times
            or []
        ),
        busy_events=(
            busy_events
            or []
        ),
        fixed_plan_items=(
            fixed_plan_items
            or []
        ),
    )


def test_weekly_available_time_becomes_free_slot():
    # 2026-10-05はMonday
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        weekly_available_times=[
            AvailableTime(
                weekday=0,
                start_minute_of_day=(
                    18 * 60
                ),
                end_minute_of_day=(
                    20 * 60
                ),
            )
        ],
    )

    assert len(result) == 1

    assert (
        result[0].start_at
        == jst(
            5,
            18,
        )
    )

    assert (
        result[0].end_at
        == jst(
            5,
            20,
        )
    )

    assert (
        result[0]
        .duration_minutes
        == 120
    )


def test_non_matching_weekday_is_not_expanded():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        weekly_available_times=[
            AvailableTime(
                weekday=1,
                start_minute_of_day=1080,
                end_minute_of_day=1200,
            )
        ],
    )

    assert result == []


def test_extra_available_time_becomes_free_slot():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        extra_available_times=[
            ExtraAvailableTime(
                start_at=jst(
                    5,
                    15,
                ),
                end_at=jst(
                    5,
                    16,
                ),
            )
        ],
    )

    assert len(result) == 1

    assert (
        result[0].start_at
        == jst(
            5,
            15,
        )
    )

    assert (
        result[0].end_at
        == jst(
            5,
            16,
        )
    )


def test_weekly_and_extra_overlap_are_merged():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        weekly_available_times=[
            AvailableTime(
                weekday=0,
                start_minute_of_day=1080,
                end_minute_of_day=1140,
            )
        ],
        extra_available_times=[
            ExtraAvailableTime(
                start_at=jst(
                    5,
                    18,
                    30,
                ),
                end_at=jst(
                    5,
                    20,
                ),
            )
        ],
    )

    assert result == [
        result[0]
    ]

    assert (
        result[0].start_at
        == jst(
            5,
            18,
        )
    )

    assert (
        result[0].end_at
        == jst(
            5,
            20,
        )
    )


def test_touching_availability_is_merged():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        weekly_available_times=[
            AvailableTime(
                weekday=0,
                start_minute_of_day=1080,
                end_minute_of_day=1140,
            )
        ],
        extra_available_times=[
            ExtraAvailableTime(
                start_at=jst(
                    5,
                    19,
                ),
                end_at=jst(
                    5,
                    20,
                ),
            )
        ],
    )

    assert len(result) == 1

    assert (
        result[0].start_at
        == jst(
            5,
            18,
        )
    )

    assert (
        result[0].end_at
        == jst(
            5,
            20,
        )
    )


def test_busy_event_splits_free_slot():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        weekly_available_times=[
            AvailableTime(
                weekday=0,
                start_minute_of_day=1080,
                end_minute_of_day=1260,
            )
        ],
        busy_events=[
            BusyEvent(
                start_at=jst(
                    5,
                    19,
                ),
                end_at=jst(
                    5,
                    20,
                ),
            )
        ],
    )

    assert len(result) == 2

    assert (
        result[0].start_at
        == jst(
            5,
            18,
        )
    )

    assert (
        result[0].end_at
        == jst(
            5,
            19,
        )
    )

    assert (
        result[1].start_at
        == jst(
            5,
            20,
        )
    )

    assert (
        result[1].end_at
        == jst(
            5,
            21,
        )
    )


def test_busy_event_overrides_extra_available_time():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        extra_available_times=[
            ExtraAvailableTime(
                start_at=jst(
                    5,
                    18,
                ),
                end_at=jst(
                    5,
                    20,
                ),
            )
        ],
        busy_events=[
            BusyEvent(
                start_at=jst(
                    5,
                    18,
                    30,
                ),
                end_at=jst(
                    5,
                    19,
                    30,
                ),
            )
        ],
    )

    assert len(result) == 2

    assert (
        result[0].start_at
        == jst(
            5,
            18,
        )
    )

    assert (
        result[0].end_at
        == jst(
            5,
            18,
            30,
        )
    )

    assert (
        result[1].start_at
        == jst(
            5,
            19,
            30,
        )
    )

    assert (
        result[1].end_at
        == jst(
            5,
            20,
        )
    )


def test_fixed_plan_item_is_subtracted():
    fixed_item = PlanItem(
        id=1,
        plan_id=1,
        study_target_id=1,
        start_at=jst(
            5,
            19,
        ),
        end_at=jst(
            5,
            20,
        ),
        origin=(
            PlanItemOrigin.USER_MODIFIED
        ),
        planned_minutes=60,
    )

    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        weekly_available_times=[
            AvailableTime(
                weekday=0,
                start_minute_of_day=1080,
                end_minute_of_day=1260,
            )
        ],
        fixed_plan_items=[
            fixed_item
        ],
    )

    assert len(result) == 2

    assert (
        result[0].end_at
        == jst(
            5,
            19,
        )
    )

    assert (
        result[1].start_at
        == jst(
            5,
            20,
        )
    )


def test_cancelled_plan_item_does_not_block_time():
    fixed_item = PlanItem(
        id=1,
        plan_id=1,
        study_target_id=1,
        start_at=jst(
            5,
            19,
        ),
        end_at=jst(
            5,
            20,
        ),
        origin=(
            PlanItemOrigin.USER_MODIFIED
        ),
        planned_minutes=60,
        is_cancelled=True,
        cancelled_at=jst(
            5,
            17,
        ),
    )

    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        weekly_available_times=[
            AvailableTime(
                weekday=0,
                start_minute_of_day=1080,
                end_minute_of_day=1260,
            )
        ],
        fixed_plan_items=[
            fixed_item
        ],
    )

    assert len(result) == 1

    assert (
        result[0].start_at
        == jst(
            5,
            18,
        )
    )

    assert (
        result[0].end_at
        == jst(
            5,
            21,
        )
    )


def test_cross_midnight_extra_time_is_split():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            7,
            0,
        ),
        extra_available_times=[
            ExtraAvailableTime(
                start_at=jst(
                    5,
                    23,
                ),
                end_at=jst(
                    6,
                    1,
                ),
            )
        ],
    )

    assert len(result) == 2

    assert (
        result[0].start_at
        == jst(
            5,
            23,
        )
    )

    assert (
        result[0].end_at
        == jst(
            6,
            0,
        )
    )

    assert (
        result[1].start_at
        == jst(
            6,
            0,
        )
    )

    assert (
        result[1].end_at
        == jst(
            6,
            1,
        )
    )


def test_slot_is_rounded_to_five_minute_grid():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        extra_available_times=[
            ExtraAvailableTime(
                start_at=jst(
                    5,
                    18,
                    2,
                ),
                end_at=jst(
                    5,
                    19,
                    58,
                ),
            )
        ],
    )

    assert len(result) == 1

    assert (
        result[0].start_at
        == jst(
            5,
            18,
            5,
        )
    )

    assert (
        result[0].end_at
        == jst(
            5,
            19,
            55,
        )
    )


def test_slot_shorter_than_ten_minutes_is_dropped():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        extra_available_times=[
            ExtraAvailableTime(
                start_at=jst(
                    5,
                    18,
                    1,
                ),
                end_at=jst(
                    5,
                    18,
                    14,
                ),
            )
        ],
    )

    # ceil -> 18:05
    # floor -> 18:10
    # 5分なのでdrop
    assert result == []


def test_exact_ten_minute_slot_is_kept():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        extra_available_times=[
            ExtraAvailableTime(
                start_at=jst(
                    5,
                    18,
                ),
                end_at=jst(
                    5,
                    18,
                    10,
                ),
            )
        ],
    )

    assert len(result) == 1

    assert (
        result[0]
        .duration_minutes
        == 10
    )


def test_availability_is_clipped_to_window():
    result = build(
        window_start=jst(
            5,
            18,
            30,
        ),
        window_end=jst(
            5,
            19,
            30,
        ),
        weekly_available_times=[
            AvailableTime(
                weekday=0,
                start_minute_of_day=1080,
                end_minute_of_day=1200,
            )
        ],
    )

    assert len(result) == 1

    assert (
        result[0].start_at
        == jst(
            5,
            18,
            30,
        )
    )

    assert (
        result[0].end_at
        == jst(
            5,
            19,
            30,
        )
    )


def test_busy_event_outside_window_has_no_effect():
    result = build(
        window_start=jst(
            5,
            18,
        ),
        window_end=jst(
            5,
            20,
        ),
        weekly_available_times=[
            AvailableTime(
                weekday=0,
                start_minute_of_day=1080,
                end_minute_of_day=1200,
            )
        ],
        busy_events=[
            BusyEvent(
                start_at=jst(
                    5,
                    10,
                ),
                end_at=jst(
                    5,
                    11,
                ),
            )
        ],
    )

    assert len(result) == 1

    assert (
        result[0].start_at
        == jst(
            5,
            18,
        )
    )

    assert (
        result[0].end_at
        == jst(
            5,
            20,
        )
    )


def test_busy_event_can_remove_entire_slot():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        extra_available_times=[
            ExtraAvailableTime(
                start_at=jst(
                    5,
                    18,
                ),
                end_at=jst(
                    5,
                    20,
                ),
            )
        ],
        busy_events=[
            BusyEvent(
                start_at=jst(
                    5,
                    17,
                ),
                end_at=jst(
                    5,
                    21,
                ),
            )
        ],
    )

    assert result == []


def test_empty_availability_returns_empty_list():
    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
    )

    assert result == []


def test_utc_extra_available_time_is_converted_to_jst():
    extra = ExtraAvailableTime(
        start_at=datetime(
            2026,
            10,
            5,
            9,
            0,
            tzinfo=UTC,
        ),
        end_at=datetime(
            2026,
            10,
            5,
            10,
            0,
            tzinfo=UTC,
        ),
    )

    result = build(
        window_start=jst(
            5,
            0,
        ),
        window_end=jst(
            6,
            0,
        ),
        extra_available_times=[
            extra
        ],
    )

    assert len(result) == 1

    assert (
        result[0].start_at
        == jst(
            5,
            18,
        )
    )

    assert (
        result[0].end_at
        == jst(
            5,
            19,
        )
    )


def test_invalid_window_is_rejected():
    dt = jst(
        5,
        18,
    )

    with pytest.raises(
        DomainValidationError,
        match=(
            "window_start must be "
            "earlier than window_end"
        ),
    ):
        build(
            window_start=dt,
            window_end=dt,
        )