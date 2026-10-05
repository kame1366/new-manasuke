from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from domain.errors import DomainValidationError


JST = ZoneInfo("Asia/Tokyo")
UTC = ZoneInfo("UTC")

DB_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def ensure_aware(
    dt: datetime,
) -> None:
    """
    datetimeがtimezone-awareであることを保証する。

    Manasuke Domainではnaive datetimeを許可しない。
    """
    if (
        dt.tzinfo is None
        or dt.utcoffset() is None
    ):
        raise DomainValidationError(
            "datetime must be timezone-aware"
        )


def now_jst() -> datetime:
    """
    現在時刻をJSTで返す。
    """
    return datetime.now(JST)


def to_utc(
    dt: datetime,
) -> datetime:
    """
    timezone-aware datetimeをUTCへ変換する。
    """
    ensure_aware(dt)

    return dt.astimezone(UTC)


def to_jst(
    dt: datetime,
) -> datetime:
    """
    timezone-aware datetimeをJSTへ変換する。
    """
    ensure_aware(dt)

    return dt.astimezone(JST)


def to_db_utc(
    dt: datetime,
) -> str:
    """
    timezone-aware datetimeを
    SQLite保存用UTC文字列へ変換する。

    例:
    2026-10-05 12:00 JST
        ->
    2026-10-05T03:00:00Z
    """
    utc_dt = to_utc(dt)

    return utc_dt.strftime(
        DB_DATETIME_FORMAT
    )


def from_db_utc(
    value: str,
) -> datetime:
    """
    SQLite保存形式のUTC文字列を
    timezone-aware datetimeへ変換する。
    """
    try:
        parsed = datetime.strptime(
            value,
            DB_DATETIME_FORMAT,
        )

    except ValueError as exc:
        raise DomainValidationError(
            f"invalid DB datetime: {value}"
        ) from exc

    return parsed.replace(
        tzinfo=UTC
    )


def ceil_to_5_minutes(
    dt: datetime,
) -> datetime:
    """
    datetimeを次の5分境界へceilする。

    例:
        10:00:00 -> 10:00
        10:01:00 -> 10:05
        10:05:00 -> 10:05
        10:05:30 -> 10:10
        10:59:00 -> 11:00
    """
    ensure_aware(dt)

    base = dt.replace(
        second=0,
        microsecond=0,
    )

    remainder = base.minute % 5

    if (
        remainder == 0
        and dt.second == 0
        and dt.microsecond == 0
    ):
        return base

    if remainder == 0:
        minutes_to_add = 5
    else:
        minutes_to_add = (
            5 - remainder
        )

    return base + timedelta(
        minutes=minutes_to_add
    )


def floor_to_5_minutes(
    dt: datetime,
) -> datetime:
    """
    datetimeを直前の5分境界へfloorする。

    例:
        10:00:00 -> 10:00
        10:04:59 -> 10:00
        10:05:00 -> 10:05
        10:09:59 -> 10:05
    """
    ensure_aware(dt)

    base = dt.replace(
        second=0,
        microsecond=0,
    )

    remainder = base.minute % 5

    return base - timedelta(
        minutes=remainder
    )


def start_of_next_day_jst(
    dt: datetime,
) -> datetime:
    """
    dtから見たJST上の翌日00:00を返す。
    """
    ensure_aware(dt)

    local = to_jst(dt)

    next_day = (
        local
        + timedelta(days=1)
    )

    return next_day.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def split_at_midnight(
    start_at: datetime,
    end_at: datetime,
) -> list[
    tuple[
        datetime,
        datetime,
    ]
]:
    """
    intervalをJSTの暦日境界で分割する。

    例:
        10/5 23:00
        ～
        10/6 01:00

    ↓

        10/5 23:00 ～ 10/6 00:00
        10/6 00:00 ～ 10/6 01:00
    """
    ensure_aware(start_at)
    ensure_aware(end_at)

    if start_at >= end_at:
        raise DomainValidationError(
            "start_at must be earlier than end_at"
        )

    start_jst = to_jst(
        start_at
    )
    end_jst = to_jst(
        end_at
    )

    result: list[
        tuple[
            datetime,
            datetime,
        ]
    ] = []

    cursor = start_jst

    while (
        cursor.date()
        < end_jst.date()
    ):
        next_midnight = datetime.combine(
            cursor.date()
            + timedelta(days=1),
            time.min,
            tzinfo=JST,
        )

        result.append(
            (
                cursor,
                next_midnight,
            )
        )

        cursor = next_midnight

    if cursor < end_jst:
        result.append(
            (
                cursor,
                end_jst,
            )
        )

    return result