from datetime import UTC, datetime, timedelta

import pytest

from chatctl.selection import cutoff_from, parse_date, parse_duration

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "days"),
    [
        ("1d", 1),
        ("90d", 90),
        ("090d", 90),
        ("2w", 14),
        ("6m", 180),
        ("1y", 365),
        ("10y", 3650),
    ],
)
def test_parse_duration_units(text, days):
    assert parse_duration(text) == timedelta(days=days)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "90",
        "d",
        "0d",
        "00w",
        "-5d",
        "+5d",
        "1.5d",
        "90x",
        "90D",
        " 90d",
        "90d ",
        "9 0d",
        "1y2d",
        "٩٠d",  # Arabic-Indic digits
    ],
)
def test_parse_duration_rejects_malformed(text):
    with pytest.raises(ValueError, match="invalid duration"):
        parse_duration(text)


def test_parse_duration_rejects_overflow_as_value_error():
    with pytest.raises(ValueError, match="too large"):
        parse_duration("999999999999d")


def test_parse_date_is_midnight_utc():
    parsed = parse_date("2026-07-01")
    assert parsed == datetime(2026, 7, 1, tzinfo=UTC)
    assert parsed.tzinfo is UTC


@pytest.mark.parametrize(
    "text",
    [
        "",
        "2026-7-1",
        "20260701",
        "2026-07-01T00:00",
        "2026-07-01Z",
        " 2026-07-01",
        "01/07/2026",
        "2026-13-01",
        "2026-02-30",
        "0000-01-01",
    ],
)
def test_parse_date_rejects_malformed(text):
    with pytest.raises(ValueError, match="invalid date"):
        parse_date(text)


def test_cutoff_from_older_than():
    assert cutoff_from(older_than=timedelta(days=90), before=None, now=NOW) == (
        NOW - timedelta(days=90)
    )


def test_cutoff_from_before():
    before = datetime(2026, 7, 1, tzinfo=UTC)
    assert cutoff_from(older_than=None, before=before, now=NOW) == before


def test_cutoff_from_requires_exactly_one():
    with pytest.raises(ValueError, match="exactly one"):
        cutoff_from(older_than=None, before=None, now=NOW)
    with pytest.raises(ValueError, match="exactly one"):
        cutoff_from(
            older_than=timedelta(days=1),
            before=datetime(2026, 7, 1, tzinfo=UTC),
            now=NOW,
        )


def test_cutoff_from_rejects_naive_now():
    with pytest.raises(ValueError, match="timezone-aware"):
        naive = datetime(2026, 1, 1)  # deliberately naive
        cutoff_from(older_than=timedelta(days=1), before=None, now=naive)


def test_cutoff_from_rejects_duration_before_year_one():
    with pytest.raises(ValueError, match="before year 1"):
        cutoff_from(older_than=parse_duration("5000y"), before=None, now=NOW)
