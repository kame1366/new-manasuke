from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from domain.errors import DomainValidationError


JST = ZoneInfo("Asia/Tokyo")
UTC = ZoneInfo("UTC")


def ensure_aware(dt: datetime) -> None:
    """Ensure that a datetime has timezone information.

    Manasuke Domainではnaive datetimeを許可しない。
    """
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DomainValidationError(
            "datetime must be timezone-aware"
        )


def now_jst() -> datetime:
    """Return the current time in JST."""
    return datetime.now(JST)


def to_utc(dt: datetime) -> datetime:
    """Convert a timezone-aware datetime to UTC."""
    ensure_aware(dt)
    return dt.astimezone(UTC)


def to_jst(dt: datetime) -> datetime:
    """Convert a timezone-aware datetime to JST."""
    ensure_aware(dt)
    return dt.astimezone(JST)


def ceil_to_5_minutes(dt: datetime) -> datetime:
    """Round a datetime up to the next 5-minute boundary.

    Examples:
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

    # 既に5分境界かつ秒以下も0なら、そのまま。
    if remainder == 0 and dt.second == 0 and dt.microsecond == 0:
        return base

    if remainder == 0:
        minutes_to_add = 5
    else:
        minutes_to_add = 5 - remainder

    return base + timedelta(minutes=minutes_to_add)


def start_of_next_day_jst(dt: datetime) -> datetime:
    """Return 00:00 JST of the next calendar day."""
    ensure_aware(dt)

    local = to_jst(dt)

    next_day = local + timedelta(days=1)

    return next_day.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )