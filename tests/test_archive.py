"""Synthetic archive selections rendered without a browser or account."""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from chatctl.archive import render_archive
from chatctl.selection import (
    Conversation,
    Selection,
    Skipped,
    SkipReason,
    select_conversations,
)

CUTOFF = datetime(2026, 10, 1, tzinfo=UTC)


def conversation(
    identifier: str, days: int = 1, title: str | None = "Placeholder"
) -> Conversation:
    return Conversation(identifier, title, CUTOFF - timedelta(days=days))


def item(identifier: str, **fields: object) -> dict[str, object]:
    return {
        "id": identifier,
        "title": "Placeholder title",
        "gizmo_id": None,
        "is_archived": False,
        "update_time": (CUTOFF - timedelta(days=1)).isoformat(),
    } | fields


def test_listing_row_counts_reconcile_with_duplicate_and_conflicting_rows():
    selection = select_conversations(
        [
            item("selected-placeholder"),
            item("selected-placeholder"),
            item("conflicting-placeholder"),
            item("conflicting-placeholder", gizmo_id="g-p-placeholder"),
            None,
        ],
        cutoff=CUTOFF,
    )
    text = render_archive(selection, cutoff=CUTOFF)
    assert "Default listing rows received: 5 (including duplicate rows)." in text
    assert "Selected: 1\nSkipped: 4\n" in text
    assert "  duplicate-id: 2\n" in text
    assert "  conflicting-duplicate: 1\n" in text
    assert "  not-an-object: 1\n" in text
    assert "conflicting-placeholder" not in text
    assert "not an authoritative account snapshot" in text
    assert "DRY RUN: no conversations modified." in text


def test_every_skip_reason_is_reported_in_enum_order_without_skipped_details():
    selection = Selection(
        (),
        tuple(
            Skipped(index, "hidden-id", "Hidden title", reason)
            for index, reason in enumerate(reversed(SkipReason))
        ),
    )
    text = render_archive(selection, cutoff=CUTOFF)
    assert f"Skipped: {len(SkipReason)}\n" in text
    lines = [line for line in text.splitlines() if line.startswith("  ")]
    assert lines == [f"  {reason.value}: 1" for reason in SkipReason]
    assert "hidden-id" not in text and "Hidden title" not in text


def test_default_samples_use_update_time_instead_of_listing_order():
    selection = Selection(
        (
            conversation("middle-placeholder", 20),
            conversation("newest-placeholder", 1),
            conversation("oldest-placeholder", 40),
            conversation("other-placeholder", 10),
        ),
        (),
    )
    text = render_archive(selection, cutoff=CUTOFF)
    assert "Oldest selected: 2026-08-22T00:00:00+00:00  oldest-placeholder" in text
    assert "Newest selected: 2026-09-30T00:00:00+00:00  newest-placeholder" in text
    assert "middle-placeholder" not in text and "other-placeholder" not in text
    assert "Skip reasons:\n  none\n" in text
    assert "bad-title" not in text


def test_list_all_includes_each_selected_row_once_in_selection_order():
    selected = (
        conversation("middle-placeholder", 20),
        conversation("newest-placeholder", 1),
        conversation("oldest-placeholder", 40),
    )
    text = render_archive(Selection(selected, ()), cutoff=CUTOFF, list_all=True)
    assert "Selected conversations (listing order):" in text
    assert "Oldest selected:" not in text and "Newest selected:" not in text
    positions = [text.index(value.id) for value in selected]
    assert positions == sorted(positions)
    assert all(text.count(value.id) == 1 for value in selected)


def test_titles_are_json_quoted_ascii_and_stay_on_single_terminal_lines():
    title = (
        'Line\n\r\t"quoted" \\ \x00\x1b[31m\x7f\x85\u202e\u2066 Caf\u00e9 \U0001f600'
    )
    selected = (conversation("escaped-placeholder", title=title),)
    text = render_archive(Selection(selected, ()), cutoff=CUTOFF, list_all=True)
    row = text.splitlines()[-1]
    assert row.endswith(json.dumps(title, ensure_ascii=True))
    assert all(character == "\n" or 32 <= ord(character) <= 126 for character in text)
    assert text.count("\n") == 9
    assert "\\n" in row and "\\u001b" in row and "\\u0085" in row
    assert "\\u202e" in row and "\\u2066" in row and "\\ud83d\\ude00" in row


def test_null_title_is_distinguishable_from_literal_titles():
    selected = (
        conversation("null-placeholder", title=None),
        conversation("literal-placeholder", title="null"),
        conversation("untitled-placeholder", title="(untitled)"),
    )
    text = render_archive(Selection(selected, ()), cutoff=CUTOFF, list_all=True)
    rows = text.splitlines()[-3:]
    assert rows[0].endswith("  null")
    assert rows[1].endswith('  "null"')
    assert rows[2].endswith('  "(untitled)"')


@pytest.mark.parametrize("list_all", [False, True])
def test_empty_listing_has_zero_counts_and_no_samples(list_all):
    text = render_archive(Selection((), ()), cutoff=CUTOFF, list_all=list_all)
    assert "Default listing rows received: 0 (including duplicate rows)." in text
    assert "Selected: 0\nSkipped: 0\nSkip reasons:\n  none\n" in text
    assert text.endswith("No conversations selected.")
    assert "selected:" not in text and "Selected conversations" not in text


@pytest.mark.parametrize("list_all", [False, True])
def test_all_skipped_lists_reasons_without_samples(list_all):
    selection = select_conversations([None], cutoff=CUTOFF)
    text = render_archive(selection, cutoff=CUTOFF, list_all=list_all)
    assert "Selected: 0\nSkipped: 1\nSkip reasons:\n  not-an-object: 1\n" in text
    assert text.endswith("No conversations selected.")
    assert "selected:" not in text and "Selected conversations" not in text


def test_single_selection_shows_the_shared_oldest_newest_sample_once():
    text = render_archive(
        Selection((conversation("only-placeholder"),), ()), cutoff=CUTOFF
    )
    assert "Oldest/newest selected:" in text
    assert text.count("only-placeholder") == 1


def test_cutoff_and_selected_timestamps_are_normalized_to_utc():
    offset = timezone(timedelta(hours=-7))
    selected = Conversation(
        "offset-placeholder", "Placeholder", datetime(2026, 9, 30, 6, tzinfo=offset)
    )
    text = render_archive(Selection((selected,), ()), cutoff=CUTOFF.astimezone(offset))
    assert (
        "Cutoff (UTC; update_time strictly before): 2026-10-01T00:00:00+00:00" in text
    )
    assert "2026-09-30T13:00:00+00:00  offset-placeholder" in text
    assert "-07:00" not in text


def test_naive_cutoff_is_rejected_instead_of_using_local_timezone():
    with pytest.raises(ValueError, match="cutoff must be timezone-aware"):
        render_archive(Selection((), ()), cutoff=CUTOFF.replace(tzinfo=None))
