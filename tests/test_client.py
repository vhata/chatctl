"""Synthetic listing fixtures only; these tests never start a browser."""

import json
from collections.abc import Iterable
from datetime import UTC, datetime

import pytest

from chatctl.client import ConversationClient
from chatctl.selection import SkipReason, select_conversations
from chatctl.transport import ClientError


def item(identifier: str = "placeholder") -> dict[str, object]:
    return {
        "id": identifier,
        "title": "Placeholder title",
        "create_time": "2020-01-01T00:00:00.123Z",
        "update_time": "2020-01-02T00:00:00Z",
        "gizmo_id": None,
        "conversation_template_id": None,
        "is_archived": False,
    }


def page(items: list[object], offset: int = 0, total: int | None = None) -> str:
    return json.dumps(
        {
            "items": items,
            "offset": offset,
            "limit": 100,
            "total": offset + len(items) if total is None else total,
        }
    )


class FakeTransport:
    def __init__(self, responses: Iterable[str | ClientError]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[int, int]] = []

    def get_page(self, offset: int, limit: int) -> str:
        self.calls.append((offset, limit))
        response = next(self.responses)
        if isinstance(response, ClientError):
            raise response
        return response


def test_moving_totals_and_raw_items_are_preserved():
    first: list[object] = [item(f"placeholder-{i}") for i in range(100)]
    second: list[object] = [item(f"placeholder-{i}") for i in range(100, 200)]
    final: list[object] = [item("last")]
    fake = FakeTransport(
        [page(first, total=101), page(second, 100, 201), page(final, 200)]
    )
    sleeps: list[float] = []
    result = ConversationClient(fake, sleep=sleeps.append).list_conversations()
    assert result == tuple(first + second + final)
    assert fake.calls == [(0, 100), (100, 100), (200, 100)]
    assert sleeps == [0.5, 0.5]


@pytest.mark.parametrize("raw", [page([]), page([], total=999)])
def test_empty_page_stops(raw):
    fake = FakeTransport([raw])
    assert ConversationClient(fake).list_conversations() == ()
    assert fake.calls == [(0, 100)]


def test_short_nonfinal_page_advances_by_actual_count():
    fake = FakeTransport([page([item()], total=101), page([], offset=1, total=101)])
    result = ConversationClient(fake, sleep=lambda _: None).list_conversations()
    assert result == (item(),)
    assert fake.calls == [(0, 100), (1, 100)]


@pytest.mark.parametrize(
    "patch",
    [
        {"items": None},
        {"items": {}},
        {"items": [None] * 101},
        {"total": None},
        {"total": True},
        {"total": -1},
        {"total": 1.0},
        {"offset": True},
        {"offset": 1},
        {"offset": None},
        {"limit": True},
        {"limit": 99},
        {"limit": None},
    ],
)
def test_invalid_envelope_fails_without_retry(patch):
    body = json.loads(page([item()]))
    body.update(patch)
    fake = FakeTransport([json.dumps(body)])
    with pytest.raises(ClientError, match="listing_shape"):
        ConversationClient(fake).list_conversations()
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "null",
        "not JSON",
        '{"items": [], "items": []}',
        '{"items":[{"gizmo_id":"g-p-placeholder","gizmo_id":null}]}',
        '{"items":[{"nested":{"x":1,"x":2}}]}',
        '{"items":[NaN]}',
        '{"items":[Infinity]}',
    ],
)
def test_malformed_and_duplicate_json_fails_closed(raw):
    fake = FakeTransport([raw])
    with pytest.raises(ClientError):
        ConversationClient(fake).list_conversations()
    assert len(fake.calls) == 1


def test_missing_membership_and_conflicting_copies_reach_selection():
    missing = item("missing")
    del missing["gizmo_id"]
    project = item("duplicate") | {"gizmo_id": "g-p-placeholder"}
    first: list[object] = [item("duplicate"), missing, None]
    fake = FakeTransport([page(first, total=101), page([project], offset=3)])
    result = ConversationClient(fake, sleep=lambda _: None).list_conversations()
    selection = select_conversations(result, cutoff=datetime(2026, 1, 1, tzinfo=UTC))
    assert not selection.selected
    assert [s.reason for s in selection.skipped] == [
        SkipReason.CONFLICTING_DUPLICATE,
        SkipReason.GIZMO_ID_MISSING,
        SkipReason.NOT_AN_OBJECT,
        SkipReason.DUPLICATE_ID,
    ]
    assert result[1] == missing and "gizmo_id" not in missing


@pytest.mark.parametrize(
    "kind,uncertain,expected",
    [
        ("http", False, [2, 4, 8]),
        ("network", False, [2, 4, 8]),
        ("timeout", False, [2, 4, 8]),
        ("runner_timeout", True, [5, 5, 8]),
    ],
)
def test_retry_exhaustion_is_bounded(kind, uncertain, expected):
    error = ClientError(kind, retryable=True, uncertain=uncertain)
    fake = FakeTransport([error] * 4)
    sleeps: list[float] = []
    with pytest.raises(ClientError):
        ConversationClient(fake, sleep=sleeps.append).list_conversations()
    assert len(fake.calls) == 4
    assert sleeps == expected


def test_retry_after_and_page_pacing_with_later_page_retry():
    first = page([item()], total=101)
    error = ClientError("http", retryable=True, status=429, retry_after=90)
    fake = FakeTransport([first, error, page([], offset=1)])
    sleeps: list[float] = []
    assert ConversationClient(fake, sleep=sleeps.append).list_conversations() == (
        item(),
    )
    assert fake.calls == [(0, 100), (1, 100), (1, 100)]
    assert sleeps == [0.5, 60]


def test_late_failure_does_not_return_partial_listing():
    fake = FakeTransport([page([item()], total=101), ClientError("http", status=401)])
    with pytest.raises(ClientError, match="401"):
        ConversationClient(fake, sleep=lambda _: None).list_conversations()
    assert len(fake.calls) == 2


def test_page_cap_does_not_return_partial_listing():
    fake = FakeTransport([page([item()], total=101)])
    with pytest.raises(ClientError, match="page_limit"):
        ConversationClient(fake, max_pages=1).list_conversations()


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_max_pages(value):
    with pytest.raises(ValueError):
        ConversationClient(FakeTransport([]), max_pages=value)
