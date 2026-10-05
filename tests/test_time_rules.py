from datetime import datetime
import pytest


from domain.errors import DomainValidationError
from domain.time_rules import (
    JST,
    UTC,
    ceil_to_5_minutes,
    ensure_aware,
    start_of_next_day_jst,
    to_jst,
    to_utc,
    to_db_utc,
    from_db_utc,
    floor_to_5_minutes,
    split_at_midnight,
)


def test_ensure_aware_accepts_timezone_aware_datetime():
    dt = datetime(
        2026,
        10,
        3,
        12,
        0,
        tzinfo=JST,
    )

    ensure_aware(dt)


def test_ensure_aware_rejects_naive_datetime():
    dt = datetime(
        2026,
        10,
        3,
        12,
        0,
    )

    with pytest.raises(
        DomainValidationError,
        match="datetime must be timezone-aware",
    ):
        ensure_aware(dt)


def test_to_utc_converts_jst_correctly():
    jst = datetime(
        2026,
        10,
        3,
        12,
        0,
        tzinfo=JST,
    )

    result = to_utc(jst)

    assert result.tzinfo == UTC
    assert result.year == 2026
    assert result.month == 10
    assert result.day == 3
    assert result.hour == 3
    assert result.minute == 0


def test_to_jst_converts_utc_correctly():
    utc = datetime(
        2026,
        10,
        3,
        3,
        0,
        tzinfo=UTC,
    )

    result = to_jst(utc)

    assert result.tzinfo == JST
    assert result.hour == 12
    assert result.minute == 0


@pytest.mark.parametrize(
    ("minute", "expected_minute"),
    [
        (0, 0),
        (1, 5),
        (4, 5),
        (5, 5),
        (6, 10),
        (9, 10),
        (10, 10),
        (56, 0),
    ],
)
def test_ceil_to_5_minutes(
    minute: int,
    expected_minute: int,
):
    dt = datetime(
        2026,
        10,
        3,
        10,
        minute,
        tzinfo=JST,
    )

    result = ceil_to_5_minutes(dt)

    assert result.minute == expected_minute
    assert result.second == 0
    assert result.microsecond == 0


def test_ceil_to_5_minutes_rolls_over_hour():
    dt = datetime(
        2026,
        10,
        3,
        10,
        56,
        tzinfo=JST,
    )

    result = ceil_to_5_minutes(dt)

    assert result.hour == 11
    assert result.minute == 0


def test_ceil_to_5_minutes_rolls_over_day():
    dt = datetime(
        2026,
        10,
        3,
        23,
        59,
        tzinfo=JST,
    )

    result = ceil_to_5_minutes(dt)

    assert result == datetime(
        2026,
        10,
        4,
        0,
        0,
        tzinfo=JST,
    )


def test_ceil_to_5_minutes_removes_seconds():
    dt = datetime(
        2026,
        10,
        3,
        10,
        5,
        30,
        tzinfo=JST,
    )

    result = ceil_to_5_minutes(dt)

    assert result == datetime(
        2026,
        10,
        3,
        10,
        10,
        tzinfo=JST,
    )


def test_start_of_next_day_jst():
    dt = datetime(
        2026,
        10,
        3,
        18,
        37,
        tzinfo=JST,
    )

    result = start_of_next_day_jst(dt)

    assert result == datetime(
        2026,
        10,
        4,
        0,
        0,
        tzinfo=JST,
    )


def test_start_of_next_day_jst_converts_from_utc():
    dt = datetime(
        2026,
        10,
        3,
        15,
        30,
        tzinfo=UTC,
    )

    result = start_of_next_day_jst(dt)

    assert result == datetime(
        2026,
        10,
        5,
        0,
        0,
        tzinfo=JST,
    )


def test_to_utc_rejects_naive_datetime():
    dt = datetime(
        2026,
        10,
        3,
        12,
        0,
    )

    with pytest.raises(
        DomainValidationError,
        match="datetime must be timezone-aware",
    ):
        to_utc(dt)


def test_to_jst_rejects_naive_datetime():
    dt = datetime(
        2026,
        10,
        3,
        12,
        0,
    )

    with pytest.raises(
        DomainValidationError,
        match="datetime must be timezone-aware",
    ):
        to_jst(dt)


def test_to_db_utc():
    dt = datetime(
        2026,
        10,
        3,
        12,
        30,
        tzinfo=JST,
    )

    assert to_db_utc(dt) == "2026-10-03T03:30:00Z"


def test_from_db_utc():
    result = from_db_utc(
        "2026-10-03T03:30:00Z"
    )

    assert result == datetime(
        2026,
        10,
        3,
        3,
        30,
        tzinfo=UTC,
    )


def test_floor_to_5_minutes_exact_boundary():
    dt = datetime(
        2026,
        10,
        6,
        10,
        5,
        tzinfo=JST,
    )

    result = floor_to_5_minutes(
        dt
    )

    assert result == datetime(
        2026,
        10,
        6,
        10,
        5,
        tzinfo=JST,
    )


def test_floor_to_5_minutes_with_seconds():
    dt = datetime(
        2026,
        10,
        6,
        10,
        9,
        59,
        tzinfo=JST,
    )

    result = floor_to_5_minutes(
        dt
    )

    assert result == datetime(
        2026,
        10,
        6,
        10,
        5,
        tzinfo=JST,
    )


def test_floor_to_5_minutes_before_first_boundary():
    dt = datetime(
        2026,
        10,
        6,
        10,
        4,
        59,
        tzinfo=JST,
    )

    result = floor_to_5_minutes(
        dt
    )

    assert result == datetime(
        2026,
        10,
        6,
        10,
        0,
        tzinfo=JST,
    )


def test_floor_to_5_minutes_rejects_naive_datetime():
    dt = datetime(
        2026,
        10,
        6,
        10,
        0,
    )

    with pytest.raises(
        DomainValidationError,
        match=(
            "datetime must be timezone-aware"
        ),
    ):
        floor_to_5_minutes(
            dt
        )


def test_split_at_midnight_same_day():
    start_at = datetime(
        2026,
        10,
        6,
        18,
        0,
        tzinfo=JST,
    )

    end_at = datetime(
        2026,
        10,
        6,
        20,
        0,
        tzinfo=JST,
    )

    result = split_at_midnight(
        start_at,
        end_at,
    )

    assert result == [
        (
            start_at,
            end_at,
        )
    ]


def test_split_at_midnight_crosses_one_midnight():
    result = split_at_midnight(
        datetime(
            2026,
            10,
            6,
            23,
            0,
            tzinfo=JST,
        ),
        datetime(
            2026,
            10,
            7,
            1,
            0,
            tzinfo=JST,
        ),
    )

    assert result == [
        (
            datetime(
                2026,
                10,
                6,
                23,
                0,
                tzinfo=JST,
            ),
            datetime(
                2026,
                10,
                7,
                0,
                0,
                tzinfo=JST,
            ),
        ),
        (
            datetime(
                2026,
                10,
                7,
                0,
                0,
                tzinfo=JST,
            ),
            datetime(
                2026,
                10,
                7,
                1,
                0,
                tzinfo=JST,
            ),
        ),
    ]


def test_split_at_midnight_exactly_ends_at_midnight():
    result = split_at_midnight(
        datetime(
            2026,
            10,
            6,
            23,
            0,
            tzinfo=JST,
        ),
        datetime(
            2026,
            10,
            7,
            0,
            0,
            tzinfo=JST,
        ),
    )

    assert result == [
        (
            datetime(
                2026,
                10,
                6,
                23,
                0,
                tzinfo=JST,
            ),
            datetime(
                2026,
                10,
                7,
                0,
                0,
                tzinfo=JST,
            ),
        )
    ]


def test_split_at_midnight_rejects_invalid_interval():
    dt = datetime(
        2026,
        10,
        6,
        20,
        0,
        tzinfo=JST,
    )

    with pytest.raises(
        DomainValidationError,
        match=(
            "start_at must be earlier than end_at"
        ),
    ):
        split_at_midnight(
            dt,
            dt,
        )