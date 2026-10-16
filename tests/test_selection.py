import copy
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pytest

from chatctl.cli import build_parser
from chatctl.selection import (
    Conversation,
    Selection,
    SkipReason,
    cutoff_from,
    parse_date,
    parse_duration,
    select_conversations,
)

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


# select_conversations ------------------------------------------------------

CUTOFF = datetime(2026, 7, 1, tzinfo=UTC)
OLD = "2026-01-15T10:00:00.000000Z"
RECENT = "2026-09-01T10:00:00.000000Z"
MISSING = object()


def item(n: int = 1, **fields: object) -> dict[str, object]:
    """A listing item shaped like a /backend-api/conversations item.

    Pass ``field=MISSING`` to drop a field.
    """
    base: dict[str, object] = {
        "id": f"conv-{n:04d}",
        "title": "Placeholder title",
        "create_time": "2025-12-01T09:00:00.000000Z",
        "update_time": OLD,
        "gizmo_id": None,
        "conversation_template_id": None,
        "is_archived": False,
        "is_starred": None,
    }
    base.update(fields)
    return {key: value for key, value in base.items() if value is not MISSING}


def select(
    items: Iterable[object],
    *,
    cutoff: datetime = CUTOFF,
    exclude: Iterable[re.Pattern[str]] = (),
) -> Selection:
    return select_conversations(items, cutoff=cutoff, exclude=exclude)


def reasons(result: Selection) -> list[SkipReason]:
    return [skip.reason for skip in result.skipped]


def test_selects_an_old_ordinary_conversation():
    result = select([item(1)])
    assert result.selected == (
        Conversation(
            id="conv-0001",
            title="Placeholder title",
            update_time=datetime(2026, 1, 15, 10, tzinfo=UTC),
        ),
    )
    assert result.skipped == ()
    assert result.selected[0].update_time.tzinfo is not None


def test_empty_input_selects_nothing():
    assert select([]) == Selection(selected=(), skipped=())


def test_accepts_a_single_pass_iterable():
    result = select(item(n) for n in range(1, 4))
    assert [c.id for c in result.selected] == ["conv-0001", "conv-0002", "conv-0003"]


def test_rejects_a_naive_cutoff():
    with pytest.raises(ValueError, match="timezone-aware"):
        select([item(1)], cutoff=datetime(2026, 7, 1))  # deliberately naive


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (None, SkipReason.NOT_AN_OBJECT),
        ("conv-0001", SkipReason.NOT_AN_OBJECT),
        (["conv-0001"], SkipReason.NOT_AN_OBJECT),
        (item(1, id=MISSING), SkipReason.BAD_ID),
        (item(1, id=None), SkipReason.BAD_ID),
        (item(1, id=""), SkipReason.BAD_ID),
        (item(1, id=1), SkipReason.BAD_ID),
        # Ids go into request paths and the manifest: only [A-Za-z0-9_-]+.
        (item(1, id="../conversations"), SkipReason.BAD_ID),
        (item(1, id="a/../b"), SkipReason.BAD_ID),
        (item(1, id=" "), SkipReason.BAD_ID),
        (item(1, id=" conv-0001"), SkipReason.BAD_ID),
        (item(1, id="x?y=1"), SkipReason.BAD_ID),
        (item(1, id="conv-0001#frag"), SkipReason.BAD_ID),
        (item(1, id="conv-0001%2F"), SkipReason.BAD_ID),
        (item(1, id="conv.0001"), SkipReason.BAD_ID),
        (item(1, id="conv-1\x00"), SkipReason.BAD_ID),
        (item(1, id="conv-1\n"), SkipReason.BAD_ID),
        (item(1, id="conv-é"), SkipReason.BAD_ID),
        (item(1, id="conv-١"), SkipReason.BAD_ID),  # Arabic-Indic digit
        (item(1, gizmo_id=MISSING), SkipReason.GIZMO_ID_MISSING),
        (item(1, gizmo_id="g-p-placeholder"), SkipReason.PROJECT_OR_CUSTOM_GPT),
        (item(1, gizmo_id="g-placeholder"), SkipReason.PROJECT_OR_CUSTOM_GPT),
        (item(1, gizmo_id=""), SkipReason.PROJECT_OR_CUSTOM_GPT),
        (item(1, gizmo_id=False), SkipReason.PROJECT_OR_CUSTOM_GPT),
        (item(1, gizmo_id={}), SkipReason.PROJECT_OR_CUSTOM_GPT),
        (
            item(1, conversation_template_id="g-p-placeholder"),
            SkipReason.CONVERSATION_TEMPLATE_ID_SET,
        ),
        (
            item(1, conversation_template_id=""),
            SkipReason.CONVERSATION_TEMPLATE_ID_SET,
        ),
        (
            item(1, conversation_template_id=False),
            SkipReason.CONVERSATION_TEMPLATE_ID_SET,
        ),
        (item(1, is_archived=True), SkipReason.ALREADY_ARCHIVED),
        (item(1, is_archived=MISSING), SkipReason.ARCHIVED_STATE_UNKNOWN),
        (item(1, is_archived=None), SkipReason.ARCHIVED_STATE_UNKNOWN),
        (item(1, is_archived=0), SkipReason.ARCHIVED_STATE_UNKNOWN),
        (item(1, is_archived="false"), SkipReason.ARCHIVED_STATE_UNKNOWN),
        (item(1, update_time=MISSING), SkipReason.BAD_UPDATE_TIME),
        (item(1, update_time=None), SkipReason.BAD_UPDATE_TIME),
        (item(1, update_time=1768471200.0), SkipReason.BAD_UPDATE_TIME),
        (item(1, update_time="not a timestamp"), SkipReason.BAD_UPDATE_TIME),
        (item(1, update_time=""), SkipReason.BAD_UPDATE_TIME),
        (item(1, update_time="2026-01-15T10:00:00"), SkipReason.BAD_UPDATE_TIME),
        (item(1, update_time="2026-01-15"), SkipReason.BAD_UPDATE_TIME),
        (item(1, update_time="2026-02-30T10:00:00Z"), SkipReason.BAD_UPDATE_TIME),
        # Valid ISO 8601, but the instant falls outside datetime's range in UTC.
        (item(1, update_time="0001-01-01T00:00:00+01:00"), SkipReason.BAD_UPDATE_TIME),
        (item(1, title=MISSING), SkipReason.BAD_TITLE),
        (item(1, title=42), SkipReason.BAD_TITLE),
        (item(1, title=["Placeholder title"]), SkipReason.BAD_TITLE),
        (item(1, update_time=RECENT), SkipReason.TOO_RECENT),
    ],
)
def test_skip_reasons(raw, reason):
    result = select([raw])
    assert result.selected == ()
    assert reasons(result) == [reason]
    assert result.skipped[0].position == 0


def test_excluded_is_a_skip_reason():
    result = select([item(1)], exclude=[re.compile("placeholder", re.IGNORECASE)])
    assert result.selected == ()
    assert reasons(result) == [SkipReason.EXCLUDED]


def test_skipped_records_id_and_title_when_usable():
    items = [
        item(1, gizmo_id="g-p-placeholder"),
        item(2, title=42),
        None,
        item(4, id="../conversations"),
    ]
    assert [(s.id, s.title) for s in select(items).skipped] == [
        ("conv-0001", "Placeholder title"),
        ("conv-0002", None),
        (None, None),
        (None, "Placeholder title"),
    ]


@pytest.mark.parametrize(
    "conversation_id",
    [
        "0f3c2a9e-1b2d-4c5e-8f7a-000000000001",
        "CONV_0001",
        "conv-0001",
        "x",
    ],
)
def test_ids_in_the_safe_character_set_are_accepted(conversation_id):
    assert [c.id for c in select([item(1, id=conversation_id)]).selected] == [
        conversation_id
    ]


def test_a_missing_conversation_template_id_is_not_doubt():
    # Only gizmo_id is required to be present; see SkipReason.
    result = select([item(1, conversation_template_id=MISSING)])
    assert [c.id for c in result.selected] == ["conv-0001"]


@pytest.mark.parametrize(
    ("update_time", "selected"),
    [
        ("2026-06-30T23:59:59.999999Z", True),
        ("2026-07-01T00:00:00Z", False),
        ("2026-07-01T00:00:00.000001Z", False),
        ("2026-07-01T00:00:00+00:00", False),
        ("2026-07-01T01:59:59+02:00", True),
        ("2026-07-01T02:00:00+02:00", False),
        ("2026-06-30T19:00:00-05:00", False),
        ("2026-06-30T18:59:59-05:00", True),
    ],
)
def test_cutoff_is_strict_and_offset_aware(update_time, selected):
    result = select([item(1, update_time=update_time)])
    if selected:
        assert [c.id for c in result.selected] == ["conv-0001"]
    else:
        assert reasons(result) == [SkipReason.TOO_RECENT]


def test_selected_update_time_keeps_its_instant():
    result = select([item(1, update_time="2026-01-15T12:00:00+02:00")])
    assert result.selected[0].update_time == datetime(2026, 1, 15, 10, tzinfo=UTC)


def test_null_title_is_selectable_and_never_excluded():
    result = select([item(1, title=None)], exclude=[re.compile(".*")])
    assert result.selected == (
        Conversation(
            id="conv-0001",
            title=None,
            update_time=datetime(2026, 1, 15, 10, tzinfo=UTC),
        ),
    )


def test_exclude_patterns_match_anywhere_in_the_title():
    items = [
        item(1, title="Placeholder title"),
        item(2, title="Another placeholder"),
        item(3, title="Something else"),
    ]
    result = select(items, exclude=[re.compile("holder")])
    assert [c.id for c in result.selected] == ["conv-0003"]
    assert reasons(result) == [SkipReason.EXCLUDED, SkipReason.EXCLUDED]


def test_exclude_patterns_are_case_insensitive_as_cli_compiles_them():
    args = build_parser().parse_args(
        ["archive", "--older-than", "90d", "--exclude", "PLACEHOLDER"]
    )
    result = select([item(1, title="a placeholder title")], exclude=args.exclude)
    assert reasons(result) == [SkipReason.EXCLUDED]


def test_any_exclude_pattern_excludes():
    items = [item(1, title="Alpha"), item(2, title="Beta"), item(3, title="Gamma")]
    patterns = [re.compile("^alpha$", re.IGNORECASE), re.compile("eta")]
    result = select(items, exclude=patterns)
    assert [c.id for c in result.selected] == ["conv-0003"]


def test_no_exclude_patterns_excludes_nothing():
    assert len(select([item(1, title="")]).selected) == 1


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        # A malformed id outranks everything after it.
        (
            item(1, id=None, gizmo_id="g-p-placeholder", update_time=RECENT),
            SkipReason.BAD_ID,
        ),
        # The gizmo checks outrank archived state, timestamps, titles and age.
        (
            item(
                1,
                gizmo_id=MISSING,
                is_archived=MISSING,
                update_time="bad",
                title=MISSING,
            ),
            SkipReason.GIZMO_ID_MISSING,
        ),
        (
            item(1, gizmo_id="g-p-placeholder", is_archived=True, update_time=RECENT),
            SkipReason.PROJECT_OR_CUSTOM_GPT,
        ),
        # A set gizmo_id is reported as such, not as the template id.
        (
            item(
                1,
                gizmo_id="g-p-placeholder",
                conversation_template_id="g-p-placeholder",
            ),
            SkipReason.PROJECT_OR_CUSTOM_GPT,
        ),
        (
            item(
                1,
                conversation_template_id="g-p-placeholder",
                is_archived=None,
                update_time=RECENT,
            ),
            SkipReason.CONVERSATION_TEMPLATE_ID_SET,
        ),
        (
            item(1, is_archived=None, update_time="bad"),
            SkipReason.ARCHIVED_STATE_UNKNOWN,
        ),
        (item(1, is_archived=True, update_time=RECENT), SkipReason.ALREADY_ARCHIVED),
        (item(1, update_time="bad", title=42), SkipReason.BAD_UPDATE_TIME),
        (item(1, title=42, update_time=RECENT), SkipReason.BAD_TITLE),
        # Age is checked before exclusion, so EXCLUDED counts only the
        # conversations a pattern kept from being archived.
        (item(1, update_time=RECENT), SkipReason.TOO_RECENT),
    ],
)
def test_reason_is_the_first_failing_check(raw, reason):
    result = select([raw], exclude=[re.compile("placeholder", re.IGNORECASE)])
    assert reasons(result) == [reason]


def test_duplicate_ids_keep_the_first_copy():
    result = select([item(1), item(2), item(1)])
    assert [c.id for c in result.selected] == ["conv-0001", "conv-0002"]
    assert [(s.id, s.reason, s.position) for s in result.skipped] == [
        ("conv-0001", SkipReason.DUPLICATE_ID, 2)
    ]


def test_a_later_copy_is_reported_as_a_duplicate_whatever_it_holds():
    result = select([item(1, update_time=RECENT), item(1, gizmo_id="g-p-placeholder")])
    assert reasons(result) == [SkipReason.TOO_RECENT, SkipReason.DUPLICATE_ID]


def test_a_skipped_first_copy_keeps_its_own_reason():
    result = select([item(1, update_time=RECENT), item(1)])
    assert result.selected == ()
    assert reasons(result) == [SkipReason.TOO_RECENT, SkipReason.DUPLICATE_ID]


@pytest.mark.parametrize(
    "later",
    [
        item(1, gizmo_id="g-p-placeholder"),
        item(1, gizmo_id=MISSING),
        item(1, conversation_template_id="g-p-placeholder"),
        item(1, is_archived=True),
        item(1, is_archived=None),
        item(1, update_time=RECENT),
        item(1, update_time="bad"),
        item(1, title=42),
        item(1, title="Excluded placeholder"),
    ],
)
def test_a_selected_copy_is_withdrawn_when_a_later_copy_would_be_skipped(later):
    patterns = [re.compile("excluded", re.IGNORECASE)]
    result = select([item(1), item(2), later], exclude=patterns)
    assert [c.id for c in result.selected] == ["conv-0002"]
    assert [(s.id, s.reason, s.position) for s in result.skipped] == [
        ("conv-0001", SkipReason.CONFLICTING_DUPLICATE, 0),
        ("conv-0001", SkipReason.DUPLICATE_ID, 2),
    ]


def test_a_later_copy_that_differs_harmlessly_does_not_withdraw():
    result = select([item(1), item(1, update_time="2026-01-16T10:00:00Z")])
    assert [c.id for c in result.selected] == ["conv-0001"]
    assert result.selected[0].update_time == datetime(2026, 1, 15, 10, tzinfo=UTC)
    assert reasons(result) == [SkipReason.DUPLICATE_ID]


def test_ids_are_compared_exactly():
    result = select([item(1, id="conv-0001"), item(2, id="CONV-0001")])
    assert len(result.selected) == 2


def test_results_keep_input_order():
    items = [
        item(1, update_time=RECENT),
        None,
        item(3),
        item(4, gizmo_id="g-p-placeholder"),
        item(5),
    ]
    result = select(items)
    assert [s.position for s in result.skipped] == [0, 1, 3]
    assert [c.id for c in result.selected] == ["conv-0003", "conv-0005"]


def test_does_not_mutate_its_input():
    items = [
        item(1),
        item(2, gizmo_id="g-p-placeholder"),
        item(3, update_time="2026-01-15T12:00:00+02:00"),
        item(1, update_time=RECENT),
        None,
    ]
    before = copy.deepcopy(items)
    select(items, exclude=[re.compile("placeholder", re.IGNORECASE)])
    assert items == before


def test_results_are_immutable():
    result = select([item(1), item(2, update_time=RECENT)])
    assert isinstance(result.selected, tuple)
    assert isinstance(result.skipped, tuple)
    # setattr, because the type checker rightly rejects a plain assignment.
    with pytest.raises(AttributeError):
        setattr(result.selected[0], "id", "conv-9999")
    with pytest.raises(AttributeError):
        setattr(result.skipped[0], "reason", SkipReason.EXCLUDED)
