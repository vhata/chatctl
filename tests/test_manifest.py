"""Synthetic journals: attribution, interruption and immutable history."""

import copy
import json
from typing import Any
from uuid import UUID

import pytest

from chatctl import manifest as m

NOW = "2026-11-09T12:00:00Z"
BINDING = "a" * 64


def uid(number: int = 1) -> str:
    return str(UUID(int=number))


def document(count: int = 1) -> m.Document:
    return m.create(
        selected=[
            {
                "id": f"synthetic-{i}",
                "title": "Private synthetic title",
                "gizmo_id": None,
                "is_archived": False,
                "update_time": "2025-01-01T00:00:00Z",
            }
            for i in range(count)
        ],
        run_id=uid(),
        now=NOW,
        binding=BINDING,
        evaluated_at=NOW,
        cutoff="2026-08-11T12:00:00Z",
        older_than="90d",
    )


def begin(
    d: m.Document, direction: str = "archive", index: int = 0, attempt: int = 2
) -> m.Document:
    return m.begin_attempt(
        d,
        f"synthetic-{index}",
        direction,
        expected_revision=d["revision"],
        now=NOW,
        attempt_id=uid(attempt),
    )


def ack(
    d: m.Document, direction: str = "archive", index: int = 0, attempt: int = 2
) -> m.Document:
    return m.acknowledge(
        d,
        f"synthetic-{index}",
        direction,
        expected_revision=d["revision"],
        now=NOW,
        attempt_id=uid(attempt),
    )


def outcome(
    d: m.Document,
    direction: str = "archive",
    index: int = 0,
    attempt: int = 2,
    **kwargs: Any,
) -> m.Document:
    return m.record_outcome(
        d,
        f"synthetic-{index}",
        direction,
        expected_revision=d["revision"],
        now=NOW,
        attempt_id=uid(attempt),
        **kwargs,
    )


def success(d: m.Document) -> m.Document:
    return outcome(ack(begin(d)), outcome="succeeded", verification_state="archived")


def test_round_trip_and_private_projection():
    d = document()
    assert m.loads(m.dumps(d)) == d
    assert m.dumps(d).endswith("\n")
    assert "Private synthetic title" not in m.dumps(d)
    assert m.account_binding("ab", "c") != m.account_binding("a", "bc")
    assert m.account_binding("a", "b") == m.account_binding("a", "b")
    assert document(0)["conversations"] == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("revision", True),
        ("schema_version", True),
        ("schema_version", 2),
        ("account_binding", "bad"),
        ("created_at", "2026-11-09"),
        ("run_id", "bad"),
        ("extra", None),
    ],
)
def test_invalid_top_level(key, value):
    d = document()
    d[key] = value
    with pytest.raises(m.ManifestError):
        m.validate(d)


@pytest.mark.parametrize(
    "text",
    [
        '{"revision": 0, "revision": 1}',
        '{"x":{"a":1,"a":2}}',
        '{"x":NaN}',
        '{"x":Infinity}',
        "[]",
        "null",
        "[" * 2000,
    ],
)
def test_strict_json(text):
    with pytest.raises(m.ManifestError):
        m.loads(text)


@pytest.mark.parametrize(
    "field,value",
    [
        ("is_archived", 0),
        ("is_archived", True),
        ("gizmo_id", "g-project"),
        ("conversation_template_id", "template"),
        ("conversation_template_id_present", 1),
        ("update_time", "2026-11-09T12:00:00Z"),
    ],
)
def test_unsafe_snapshot(field, value):
    d = document()
    d["conversations"][0]["original"][field] = value
    with pytest.raises(m.ManifestError):
        m.validate(d)


def test_duplicate_ids_attempts_unknown_fields_and_cutoff():
    d = document()
    d["conversations"].append(copy.deepcopy(d["conversations"][0]))
    with pytest.raises(m.ManifestError):
        m.validate(d)
    d = document()
    d["selection"]["cutoff"] = NOW
    with pytest.raises(m.ManifestError):
        m.validate(d)
    d = begin(document(2))
    with pytest.raises(m.ManifestError):
        begin(d, index=1)
    d = document()
    d["conversations"][0]["archive"]["secret"] = "never accepted"
    with pytest.raises(m.ManifestError):
        m.validate(d)


def test_success_requires_separate_ack_and_verification():
    d = begin(document())
    with pytest.raises(m.ManifestError):
        outcome(
            d,
            outcome="succeeded",
            verification_state="archived",
            quiescent_basis="request_completed",
        )
    a = ack(d)
    assert d["conversations"][0]["archive"]["attempts"][0]["acknowledged"] is False
    with pytest.raises(m.ManifestError):
        outcome(a, outcome="succeeded", verification_state="active")
    s = outcome(a, outcome="succeeded", verification_state="archived")
    assert s["conversations"][0]["undo"]["status"] == "pending"
    assert m.holds([s]) == (False, frozenset())
    forged = copy.deepcopy(s)
    forged["revision"] = d["revision"] + 1
    with pytest.raises(m.ManifestError):
        m.validate_transition(d, forged, d["revision"])


def test_owned_undo_seals_archive_and_preserves_history():
    d = success(document(2))
    with pytest.raises(m.ManifestError):
        begin(d, "undo", attempt=3)
    sealed = m.start_undo(d, expected_revision=d["revision"], now=NOW)
    with pytest.raises(m.ManifestError):
        begin(sealed, index=1, attempt=4)
    undo = begin(sealed, "undo", attempt=3)
    bypass = copy.deepcopy(undo)
    bypass["revision"] = d["revision"] + 1
    with pytest.raises(m.ManifestError):
        m.validate_transition(d, bypass, d["revision"])
    undone = outcome(
        ack(undo, "undo", attempt=3),
        "undo",
        attempt=3,
        outcome="succeeded",
        verification_state="active",
    )
    assert undone["conversations"][0]["archive"] == d["conversations"][0]["archive"]
    with pytest.raises(m.ManifestError):
        begin(undone, "undo", attempt=4)


def test_unknown_quiescence_and_late_result_after_undo_seal():
    d = begin(success(document(2)), index=1, attempt=3)
    d = outcome(
        d, index=1, attempt=3, outcome="unknown", error_code="transport_unknown"
    )
    assert m.holds([d]) == (True, frozenset({(BINDING, "synthetic-1")}))
    with pytest.raises(m.ManifestError):
        begin(d, index=1, attempt=4)
    d = m.start_undo(d, expected_revision=d["revision"], now=NOW)
    d = outcome(
        d,
        index=1,
        attempt=3,
        outcome="unknown",
        verification_state="archived",
        quiescent_basis="execution_stopped",
    )
    assert m.holds([d]) == (False, frozenset({(BINDING, "synthetic-1")}))
    assert d["conversations"][1]["undo"]["status"] == "not_eligible"
    d = ack(d, index=1, attempt=3)
    d = outcome(
        d, index=1, attempt=3, outcome="succeeded", verification_state="archived"
    )
    attempt = d["conversations"][1]["archive"]["attempts"][0]
    assert attempt["error_code"] == "transport_unknown"
    assert attempt["execution"]["basis"] == "execution_stopped"
    assert m.holds([d]) == (False, frozenset())


def test_interrupted_intent_never_replayed():
    d = begin(document())
    assert m.holds([m.loads(m.dumps(d))])[0]
    d = m.interrupted(
        d, "synthetic-0", "archive", expected_revision=d["revision"], now=NOW
    )
    assert d["conversations"][0]["archive"]["status"] == "unknown"
    with pytest.raises(m.ManifestError):
        begin(d, attempt=3)
    with pytest.raises(m.ManifestError):
        m.skip(
            d,
            "synthetic-0",
            "archive",
            expected_revision=d["revision"],
            now=NOW,
            reason="already_archived",
        )


def test_definite_failure_retry_and_skip_preserve_history():
    failed = outcome(
        begin(document()),
        outcome="failed",
        error_code="not_dispatched",
        quiescent_basis="not_dispatched",
    )
    retried = begin(failed, attempt=3)
    assert len(retried["conversations"][0]["archive"]["attempts"]) == 2
    skipped = m.skip(
        failed,
        "synthetic-0",
        "archive",
        expected_revision=failed["revision"],
        now=NOW,
        reason="membership_changed",
    )
    assert (
        skipped["conversations"][0]["archive"]["attempts"]
        == failed["conversations"][0]["archive"]["attempts"]
    )
    with pytest.raises(m.ManifestError):
        outcome(
            begin(document()),
            outcome="failed",
            error_code="transport_unknown",
            http_status=500,
            quiescent_basis="request_completed",
        )


@pytest.mark.parametrize("field", m.IMMUTABLE)
def test_immutable_transition_fields(field):
    d = document()
    changed = begin(d)
    changed[field] = None
    with pytest.raises(m.ManifestError):
        m.validate_transition(d, changed, 0)


def test_stale_revision_and_history_rewrite():
    d = success(document())
    with pytest.raises(m.ManifestError):
        m.start_undo(d, expected_revision=0, now=NOW)
    changed = copy.deepcopy(d)
    changed["revision"] += 1
    changed["conversations"][0]["archive"]["attempts"][0]["http_status"] = 201
    with pytest.raises(m.ManifestError):
        m.validate_transition(d, changed, d["revision"])


def test_document_rejects_nonfinite_values_anywhere():
    text = json.dumps(document()).replace('"revision": 0', '"revision": NaN')
    with pytest.raises(m.ManifestError):
        m.loads(text)


def test_undo_seal_cannot_share_an_archive_intent_checkpoint():
    d = document()
    forged = begin(d)
    forged["undo_started_at"] = NOW
    with pytest.raises(m.ManifestError, match="own checkpoint"):
        m.validate_transition(d, forged, 0)
