"""Aggregate synthetic listing observations without a browser or account."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone

import pytest

from chatctl.stats import AGES, ARCHIVE_STATES, KINDS, render_stats, summarise

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


def item(identifier: str = "placeholder", **fields: object) -> dict[str, object]:
    return {
        "id": identifier,
        "title": "Placeholder title",
        "gizmo_id": None,
        "is_archived": False,
        "update_time": (NOW - timedelta(days=60)).isoformat(),
    } | fields


def test_empty_listing_has_every_category_and_zero_counts():
    result = summarise([], now=NOW)
    assert result.rows == result.total == result.duplicates == result.unidentified == 0
    assert result.conflicts == 0 and result.ids == frozenset()
    assert result.kinds == dict.fromkeys(KINDS, 0)
    assert result.archive_states == dict.fromkeys(ARCHIVE_STATES, 0)
    assert result.ages == dict.fromkeys(AGES, 0)


@pytest.mark.parametrize(
    "fields,expected",
    [
        ({"gizmo_id": None}, "ordinary"),
        ({"gizmo_id": "g-p-placeholder"}, "project"),
        ({"gizmo_id": "g-placeholder"}, "custom GPT"),
        ({"gizmo_id": "unknown-prefix"}, "unknown"),
        ({"gizmo_id": "g-p-"}, "unknown"),
        ({"gizmo_id": "g-"}, "unknown"),
        ({"gizmo_id": ""}, "unknown"),
        ({"gizmo_id": True}, "unknown"),
        ({"gizmo_id": []}, "unknown"),
        ({"gizmo_id": {}}, "unknown"),
        ({"gizmo_id": None, "conversation_template_id": "placeholder"}, "unknown"),
    ],
)
def test_kind_classification(fields, expected):
    result = summarise([item(**fields)], now=NOW)
    assert result.kinds[expected] == 1
    assert sum(result.kinds.values()) == 1


def test_missing_kind_does_not_mean_ordinary():
    missing = item()
    del missing["gizmo_id"]
    assert summarise([missing], now=NOW).kinds["unknown"] == 1


@pytest.mark.parametrize(
    "state,expected",
    [
        (True, "archived"),
        (False, "unarchived"),
        (None, "unknown"),
        (0, "unknown"),
        (1, "unknown"),
        ("false", "unknown"),
        ([], "unknown"),
    ],
)
def test_archive_state_requires_exact_boolean(state, expected):
    result = summarise([item(is_archived=state)], now=NOW)
    assert result.archive_states[expected] == 1
    assert sum(result.archive_states.values()) == 1


def test_missing_archive_state_is_unknown():
    missing = item()
    del missing["is_archived"]
    assert summarise([missing], now=NOW).archive_states["unknown"] == 1


@pytest.mark.parametrize(
    "elapsed,expected",
    [
        (timedelta(microseconds=-1), "future"),
        (timedelta(0), "under 30 days"),
        (timedelta(days=30, microseconds=-1), "under 30 days"),
        (timedelta(days=30), "30–89 days"),
        (timedelta(days=90, microseconds=-1), "30–89 days"),
        (timedelta(days=90), "90–364 days"),
        (timedelta(days=365, microseconds=-1), "90–364 days"),
        (timedelta(days=365), "365+ days"),
        (timedelta(days=2000), "365+ days"),
    ],
)
def test_age_boundaries(elapsed, expected):
    result = summarise([item(update_time=(NOW - elapsed).isoformat())], now=NOW)
    assert result.ages[expected] == 1
    assert sum(result.ages.values()) == 1


@pytest.mark.parametrize(
    "value",
    [
        None,
        123,
        True,
        "bad",
        "2026-01-01",
        "2026-01-01T12:00:00",
        "0001-01-01T00:00:00+23:59",
    ],
)
def test_unknown_age(value):
    assert summarise([item(update_time=value)], now=NOW).ages["unknown"] == 1


def test_missing_timestamp_and_nonobjects_count_as_unknown():
    missing = item()
    del missing["update_time"]
    result = summarise([missing, None, "placeholder", []], now=NOW)
    assert result.total == result.rows == 4
    assert result.unidentified == 3
    assert result.ages["unknown"] == 4
    assert result.kinds == {"ordinary": 1, "project": 0, "custom GPT": 0, "unknown": 3}


def test_offsets_and_fractional_seconds_are_normalised_and_creation_time_is_unused():
    at_cutoff = (NOW - timedelta(days=90)).astimezone(timezone(timedelta(hours=-7)))
    result = summarise(
        [item(update_time=at_cutoff.isoformat(), create_time=NOW.isoformat())],
        now=NOW.astimezone(timezone(timedelta(hours=4))),
    )
    assert result.ages["90–364 days"] == 1
    assert (
        summarise([item(update_time="2026-10-26T11:59:59.123Z")], now=NOW).ages[
            "under 30 days"
        ]
        == 1
    )


def test_naive_clock_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        summarise([], now=NOW.replace(tzinfo=None))


def test_duplicate_categories_collapse_and_conflicts_are_unknown_per_dimension():
    ordinary = item()
    conflict = item(
        gizmo_id="g-p-placeholder", update_time=(NOW - timedelta(days=400)).isoformat()
    )
    result = summarise([ordinary, conflict, ordinary], now=NOW)
    assert result.rows == 3 and result.total == 1
    assert result.duplicates == 2 and result.conflicts == 1
    assert result.kinds["unknown"] == result.ages["unknown"] == 1
    assert result.archive_states["unarchived"] == 1
    agreeing = summarise([ordinary, ordinary], now=NOW)
    assert agreeing.duplicates == 1 and agreeing.conflicts == 0
    assert agreeing.kinds["ordinary"] == 1


def test_duplicate_archive_state_conflict_does_not_hide_other_categories():
    result = summarise([item(), item(is_archived=True)], now=NOW)
    assert result.archive_states["unknown"] == 1
    assert result.kinds["ordinary"] == result.ages["30–89 days"] == 1


def test_unusable_ids_stay_counted_and_dimensions_reconcile_without_mutation():
    items = [
        item(),
        item(),
        item(identifier=""),
        item(id=None),
        item(id=5),
        item(identifier=" "),
        None,
    ]
    original = deepcopy(items)
    result = summarise(iter(items), now=NOW)
    assert items == original
    assert result.rows == 7 and result.total == 6
    assert result.unidentified == 5 and result.duplicates == 1
    assert (
        sum(result.kinds.values())
        == sum(result.archive_states.values())
        == sum(result.ages.values())
        == result.total
    )


def test_overlap_is_visible_without_claiming_a_combined_account_total_or_leaking_items():
    default = summarise([item()], now=NOW)
    archived = summarise([item(is_archived=True, update_time=NOW.isoformat())], now=NOW)
    text = render_stats(default, archived)
    assert "IDs present in both listings: 1" in text
    assert "not an authoritative account snapshot" in text
    assert "Archive state (reported is_archived)" in text
    assert "Age (since update_time)" in text
    assert text.count("Counted items: 1") == 2
    assert "placeholder" not in text and "Placeholder title" not in text
    assert "placeholder" not in repr(default)
