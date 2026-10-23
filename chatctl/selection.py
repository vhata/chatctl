"""Pure helpers for turning command-line criteria into an archive cutoff.

A conversation is selected for archiving when its ``update_time`` is
strictly earlier than the cutoff.
"""

import re
from datetime import UTC, date, datetime, timedelta

_UNIT_DAYS = {"d": 1, "w": 7, "m": 30, "y": 365}
_DURATION_RE = re.compile(r"([0-9]+)([dwmy])")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_duration(text: str) -> timedelta:
    """Parse a duration such as ``90d``, ``2w``, ``6m`` or ``1y``.

    Months are a fixed 30 days and years a fixed 365 days.
    """
    match = _DURATION_RE.fullmatch(text)
    if match is None or int(match.group(1)) == 0:
        raise ValueError(
            f"invalid duration {text!r}: expected a positive whole number "
            "followed by d, w, m or y (for example 90d)"
        )
    count, unit = match.groups()
    try:
        return timedelta(days=int(count) * _UNIT_DAYS[unit])
    except OverflowError:
        raise ValueError(f"invalid duration {text!r}: too large") from None


def parse_date(text: str) -> datetime:
    """Parse ``YYYY-MM-DD`` as midnight UTC on that date."""
    if _DATE_RE.fullmatch(text) is None:
        raise ValueError(f"invalid date {text!r}: expected YYYY-MM-DD")
    try:
        day = date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"invalid date {text!r}: no such day") from None
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def cutoff_from(
    *,
    older_than: timedelta | None,
    before: datetime | None,
    now: datetime,
) -> datetime:
    """Return the archive cutoff for exactly one of ``older_than`` or ``before``."""
    if (older_than is None) == (before is None):
        raise ValueError("exactly one of older_than or before is required")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if before is not None:
        return before
    # The exactly-one check above guarantees this; the type checker cannot
    # follow it through the comparison.
    assert older_than is not None
    try:
        return now - older_than
    except OverflowError:
        raise ValueError(f"duration {older_than} reaches before year 1") from None
