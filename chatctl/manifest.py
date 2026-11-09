"""Offline version-1 archive journal. No clocks, credentials or network I/O.

Documents are ordinary JSON dictionaries. Public operations validate and
copy their inputs; callers persist each returned revision before proceeding.
Evidence arguments are assertions by a future, evidence-backed transport,
not conclusions this module can draw from a response code or listing.
"""

import copy
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from chatctl.selection import (
    cutoff_from,
    parse_date,
    parse_duration,
    select_conversations,
)

Document = dict[str, Any]
REASONS = frozenset(
    {
        "membership_changed",
        "selection_changed",
        "already_active",
        "already_archived",
        "state_conflict",
        "definite_rejection",
        "transport_unknown",
        "interrupted",
        "not_dispatched",
        "authentication_failed",
        "read_unavailable",
    }
)
SKIP_REASONS = frozenset(
    {
        "membership_changed",
        "selection_changed",
        "already_active",
        "already_archived",
        "state_conflict",
        "read_unavailable",
    }
)
ERROR_CODES = frozenset(
    {
        "definite_rejection",
        "not_dispatched",
        "transport_unknown",
        "interrupted",
        "authentication_failed",
        "state_conflict",
        "read_unavailable",
    }
)
STATUSES = frozenset(
    {"pending", "skipped", "in_flight", "succeeded", "failed", "unknown"}
)
IMMUTABLE = (
    "schema_version",
    "run_id",
    "operation",
    "created_at",
    "account_binding",
    "selection",
)


class ManifestError(ValueError):
    """Invalid document or unsafe transition; messages never contain input data."""


def _require(condition: bool, message: str = "invalid manifest") -> None:
    if not condition:
        raise ManifestError(message)


def _object(value: Any, keys: str) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == set(keys.split()), "invalid object fields"
    )
    return value  # type: ignore[no-any-return]


def _time(value: Any) -> datetime:
    _require(
        isinstance(value, str)
        and bool(
            re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value)
        ),
        "invalid UTC timestamp",
    )
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ManifestError("invalid UTC timestamp") from None


def _uuid(value: Any) -> None:
    try:
        _require(isinstance(value, str) and str(UUID(value)) == value, "invalid UUID")
    except (ValueError, AttributeError):
        raise ManifestError("invalid UUID") from None


def _enum(value: Any, allowed: Iterable[str], *, nullable: bool = False) -> None:
    _require(
        (nullable and value is None) or (isinstance(value, str) and value in allowed),
        "invalid enumerated value",
    )


def account_binding(user_identity: str, workspace_identity: str) -> str:
    """Hash caller-proven stable identities, never tab IDs or session objects."""
    _require(
        type(user_identity) is str
        and bool(user_identity)
        and type(workspace_identity) is str
        and bool(workspace_identity),
        "identity unavailable",
    )
    encoded = json.dumps(
        ["chatctl-account-v1", user_identity, workspace_identity],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _selection(value: Any) -> datetime:
    s = _object(value, "evaluated_at cutoff criteria")
    now, cutoff = _time(s["evaluated_at"]), _time(s["cutoff"])
    c = _object(s["criteria"], "older_than before exclude")
    _require(
        (c["older_than"] is None) != (c["before"] is None), "one cutoff input required"
    )
    _require(
        type(c["exclude"]) is list and all(type(p) is str for p in c["exclude"]),
        "invalid exclusions",
    )
    try:
        for p in c["exclude"]:
            re.compile(p, re.IGNORECASE)
        _require(c["older_than"] is None or type(c["older_than"]) is str)
        _require(c["before"] is None or type(c["before"]) is str)
        expected = cutoff_from(
            older_than=parse_duration(c["older_than"])
            if c["older_than"] is not None
            else None,
            before=parse_date(c["before"]) if c["before"] is not None else None,
            now=now,
        )
    except (ValueError, OverflowError, RecursionError, re.error):
        raise ManifestError("invalid selection criteria") from None
    _require(cutoff == expected, "cutoff does not match criteria")
    return cutoff


def _attempt(value: Any, direction: str, identities: set[str]) -> None:
    a = _object(
        value,
        "attempt_id started_at finished_at outcome error_code http_status acknowledged verification execution",
    )
    _uuid(a["attempt_id"])
    _require(a["attempt_id"] not in identities, "duplicate attempt ID")
    identities.add(a["attempt_id"])
    _time(a["started_at"])
    _enum(a["outcome"], {"in_flight", "succeeded", "failed", "unknown"})
    _enum(a["error_code"], ERROR_CODES, nullable=True)
    _require(
        a["http_status"] is None
        or (type(a["http_status"]) is int and 100 <= a["http_status"] <= 599),
        "invalid HTTP status",
    )
    _require(type(a["acknowledged"]) is bool)
    if a["finished_at"] is not None:
        _time(a["finished_at"])
    _require(
        (a["outcome"] == "in_flight") == (a["finished_at"] is None),
        "invalid completion time",
    )
    e = _object(a["execution"], "state confirmed_at basis")
    _enum(e["state"], {"may_execute", "quiescent"})
    if e["state"] == "may_execute":
        _require(e["confirmed_at"] is None and e["basis"] is None)
    else:
        _time(e["confirmed_at"])
        _enum(e["basis"], {"not_dispatched", "request_completed", "execution_stopped"})
    v = a["verification"]
    if v is not None:
        _object(v, "checked_at state")
        _time(v["checked_at"])
        _enum(v["state"], {"active", "archived", "conflicting", "unavailable"})
    if a["acknowledged"]:
        _require(
            e["state"] == "quiescent"
            and e["basis"] in {"request_completed", "execution_stopped"},
            "acknowledgement requires completed request",
        )
        _require(type(a["http_status"]) is int and 200 <= a["http_status"] < 300)
    if e["basis"] == "not_dispatched":
        _require(not a["acknowledged"] and a["http_status"] is None)
    if a["outcome"] in {"succeeded", "failed"}:
        _require(e["state"] == "quiescent", "terminal outcome requires quiescence")
    if a["outcome"] == "succeeded":
        _require(
            a["acknowledged"]
            and v is not None
            and v["state"] == ("archived" if direction == "archive" else "active"),
            "success requires attributable verification",
        )
    if a["outcome"] == "failed":
        _require(
            not a["acknowledged"]
            and a["error_code"] in {"not_dispatched", "definite_rejection"},
            "failure needs definite non-application",
        )
        _require(a["error_code"] != "not_dispatched" or e["basis"] == "not_dispatched")
    if a["outcome"] == "unknown":
        _require(a["error_code"] is not None, "unknown needs a bounded error")


def validate(document: Any) -> None:
    """Reject the entire document on any unknown or inconsistent value."""
    d = _object(
        document,
        "schema_version run_id operation created_at updated_at revision account_binding selection undo_started_at conversations",
    )
    _require(
        type(d["schema_version"]) is int and d["schema_version"] == 1,
        "unsupported schema",
    )
    _uuid(d["run_id"])
    _require(d["operation"] == "archive")
    _time(d["created_at"])
    _time(d["updated_at"])
    _require(type(d["revision"]) is int and d["revision"] >= 0, "invalid revision")
    _require(
        type(d["account_binding"]) is str
        and bool(re.fullmatch("[0-9a-f]{64}", d["account_binding"])),
        "invalid account binding",
    )
    cutoff = _selection(d["selection"])
    if d["undo_started_at"] is not None:
        _time(d["undo_started_at"])
    _require(type(d["conversations"]) is list)
    ids: set[str] = set()
    attempts: set[str] = set()
    for row in d["conversations"]:
        r = _object(row, "id original archive undo")
        _require(
            type(r["id"]) is str
            and bool(re.fullmatch("[A-Za-z0-9_-]+", r["id"], re.ASCII))
            and r["id"] not in ids,
            "invalid or repeated conversation ID",
        )
        ids.add(r["id"])
        o = _object(
            r["original"],
            "update_time is_archived gizmo_id conversation_template_id_present conversation_template_id",
        )
        _require(_time(o["update_time"]) < cutoff, "snapshot outside cutoff")
        _require(
            o["is_archived"] is False
            and o["gizmo_id"] is None
            and o["conversation_template_id"] is None
            and type(o["conversation_template_id_present"]) is bool,
            "unsafe membership snapshot",
        )
        for direction in ("archive", "undo"):
            rec = _object(r[direction], "status reason attempts")
            _enum(
                rec["status"],
                STATUSES | ({"not_eligible"} if direction == "undo" else set()),
            )
            _enum(rec["reason"], REASONS, nullable=True)
            _require(type(rec["attempts"]) is list)
            for attempt in rec["attempts"]:
                _attempt(attempt, direction, attempts)
            history = rec["attempts"]
            _require(
                all(a["outcome"] == "failed" for a in history[:-1]),
                "only definite failures permit another attempt",
            )
            if rec["status"] in {"pending", "not_eligible"}:
                _require(not history and rec["reason"] is None)
            elif rec["status"] == "skipped":
                _require(
                    rec["reason"] in SKIP_REASONS
                    and all(a["outcome"] == "failed" for a in history)
                )
            else:
                _require(
                    bool(history) and history[-1]["outcome"] == rec["status"],
                    "status and attempt disagree",
                )
            if direction == "undo":
                _require(
                    (rec["status"] == "not_eligible")
                    == (r["archive"]["status"] != "succeeded"),
                    "undo requires owned archive",
                )
                _require(
                    (not history and rec["status"] != "skipped")
                    or d["undo_started_at"] is not None,
                    "undo phase not sealed",
                )


def dumps(document: Document) -> str:
    validate(document)
    return json.dumps(document, ensure_ascii=True, allow_nan=False, indent=2) + "\n"


def loads(text: str) -> Document:
    def pairs(entries: list[tuple[str, Any]]) -> Document:
        result: Document = {}
        for key, value in entries:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(_: str) -> Any:
        raise ManifestError("non-finite JSON value")

    try:
        document = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        validate(document)
        return document  # type: ignore[no-any-return]
    except (ValueError, RecursionError, UnicodeError):
        raise ManifestError("invalid manifest JSON") from None


def create(
    *,
    selected: Sequence[Mapping[str, object]],
    run_id: str,
    now: str,
    binding: str,
    evaluated_at: str,
    cutoff: str,
    older_than: str | None = None,
    before: str | None = None,
    exclude: Sequence[str] = (),
) -> Document:
    """Freeze a complete already-selected snapshot, omitting private titles.

    All supplied rows must pass the selector, including duplicate checks.
    The caller supplies the full selection, not a lazy stream of candidates.
    """
    selection = {
        "evaluated_at": evaluated_at,
        "cutoff": cutoff,
        "criteria": {
            "older_than": older_than,
            "before": before,
            "exclude": list(exclude),
        },
    }
    cutoff_dt = _selection(selection)
    checked = select_conversations(
        selected,
        cutoff=cutoff_dt,
        exclude=[re.compile(p, re.IGNORECASE) for p in exclude],
    )
    _require(
        not checked.skipped and len(checked.selected) == len(selected),
        "unsafe selection",
    )
    rows = []
    for raw, conversation in zip(selected, checked.selected, strict=True):
        rows.append(
            {
                "id": conversation.id,
                "original": {
                    "update_time": conversation.update_time.astimezone(UTC)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "is_archived": False,
                    "gizmo_id": None,
                    "conversation_template_id_present": "conversation_template_id"
                    in raw,
                    "conversation_template_id": None,
                },
                "archive": {"status": "pending", "reason": None, "attempts": []},
                "undo": {"status": "not_eligible", "reason": None, "attempts": []},
            }
        )
    result = {
        "schema_version": 1,
        "run_id": run_id,
        "operation": "archive",
        "created_at": now,
        "updated_at": now,
        "revision": 0,
        "account_binding": binding,
        "selection": selection,
        "undo_started_at": None,
        "conversations": rows,
    }
    validate(result)
    return result


def validate_transition(old: Document, new: Document, expected_revision: int) -> None:
    """Independently enforce write-once fields and evidence-preserving history."""
    validate(old)
    validate(new)
    _require(
        type(expected_revision) is int
        and old["revision"] == expected_revision
        and new["revision"] == expected_revision + 1,
        "stale revision",
    )
    _require(all(old[k] == new[k] for k in IMMUTABLE), "immutable fields changed")
    _require(
        old["undo_started_at"] is None
        or old["undo_started_at"] == new["undo_started_at"],
        "undo seal changed",
    )
    _require(
        len(old["conversations"]) == len(new["conversations"]), "selection changed"
    )
    changed_records = 0
    for previous, current in zip(
        old["conversations"], new["conversations"], strict=True
    ):
        _require(
            previous["id"] == current["id"]
            and previous["original"] == current["original"],
            "selection changed",
        )
        for direction in ("archive", "undo"):
            a, b = previous[direction], current[direction]
            if a == b:
                continue
            # Archive success makes the previously ineligible undo pending.
            if (
                direction == "undo"
                and a["status"] == "not_eligible"
                and b["status"] == "pending"
                and current["archive"]["status"] == "succeeded"
            ):
                continue
            changed_records += 1
            _require(
                a["status"] not in {"skipped", "succeeded", "not_eligible"},
                "terminal direction changed",
            )
            x, y = a["attempts"], b["attempts"]
            _require(len(y) in {len(x), len(x) + 1}, "history removed")
            if len(y) > len(x):
                _require(
                    direction != "archive" or old["undo_started_at"] is None,
                    "archive phase sealed",
                )
                _require(
                    direction != "undo" or old["undo_started_at"] is not None,
                    "persist undo seal before intent",
                )
                _require(
                    a["status"] in {"pending", "failed"}
                    and y[:-1] == x
                    and b["status"] == "in_flight",
                    "unsafe retry",
                )
                intent = y[-1]
                _require(
                    intent["outcome"] == "in_flight"
                    and not intent["acknowledged"]
                    and intent["verification"] is None
                    and intent["error_code"] is None
                    and intent["http_status"] is None
                    and intent["execution"]["state"] == "may_execute",
                    "invalid intent",
                )
            elif b["status"] == "skipped":
                _require(
                    direction != "archive" or old["undo_started_at"] is None,
                    "archive phase sealed",
                )
                _require(a["status"] in {"pending", "failed"} and y == x, "unsafe skip")
            else:
                _require(
                    bool(x)
                    and y[:-1] == x[:-1]
                    and a["status"] in {"in_flight", "unknown"},
                    "history rewritten",
                )
                p, q = x[-1], y[-1]
                _require(
                    p["attempt_id"] == q["attempt_id"]
                    and p["started_at"] == q["started_at"],
                    "attempt identity changed",
                )
                _require(
                    not p["acknowledged"] or q["acknowledged"], "acknowledgement lost"
                )
                _require(
                    p["error_code"] is None or p["error_code"] == q["error_code"],
                    "error evidence lost",
                )
                _require(
                    p["http_status"] is None or p["http_status"] == q["http_status"],
                    "HTTP evidence lost",
                )
                _require(
                    p["execution"]["state"] != "quiescent"
                    or p["execution"] == q["execution"],
                    "quiescence evidence changed",
                )
                _require(
                    p["finished_at"] is None or p["finished_at"] == q["finished_at"],
                    "completion evidence changed",
                )
                if a["status"] == "unknown":
                    _require(
                        b["status"] in {"unknown", "succeeded"},
                        "unknown replayed or discarded",
                    )
                if b["status"] == "succeeded":
                    _require(
                        p["acknowledged"],
                        "checkpoint acknowledgement before verification",
                    )
                if not p["acknowledged"] and q["acknowledged"]:
                    _require(
                        p["verification"] == q["verification"]
                        and p["outcome"] == q["outcome"],
                        "acknowledgement needs its own checkpoint",
                    )
                if p["verification"] is not None and q["verification"] is None:
                    raise ManifestError("verification evidence lost")
    _require(changed_records <= 1, "one direction per checkpoint required")


def _edit(document: Document, expected_revision: int, now: str) -> Document:
    validate(document)
    _require(
        type(expected_revision) is int and expected_revision == document["revision"],
        "stale revision",
    )
    _time(now)
    result = copy.deepcopy(document)
    result["revision"] += 1
    result["updated_at"] = now
    return result


def _record(document: Document, conversation_id: str, direction: str) -> Document:
    _enum(direction, {"archive", "undo"})
    for row in document["conversations"]:
        if row["id"] == conversation_id:
            return row[direction]  # type: ignore[no-any-return]
    raise ManifestError("conversation outside manifest")


def _done(old: Document, new: Document, expected_revision: int) -> Document:
    validate_transition(old, new, expected_revision)
    return new


def start_undo(document: Document, *, expected_revision: int, now: str) -> Document:
    new = _edit(document, expected_revision, now)
    _require(new["undo_started_at"] is None, "undo already started")
    new["undo_started_at"] = now
    return _done(document, new, expected_revision)


def begin_attempt(
    document: Document,
    conversation_id: str,
    direction: str,
    *,
    expected_revision: int,
    now: str,
    attempt_id: str,
) -> Document:
    new = _edit(document, expected_revision, now)
    rec = _record(new, conversation_id, direction)
    _require(rec["status"] in {"pending", "failed"}, "direction cannot dispatch")
    _require(
        direction != "undo" or new["undo_started_at"] is not None,
        "persist undo seal before intent",
    )
    rec.update(status="in_flight", reason=None)
    rec["attempts"].append(
        {
            "attempt_id": attempt_id,
            "started_at": now,
            "finished_at": None,
            "outcome": "in_flight",
            "error_code": None,
            "http_status": None,
            "acknowledged": False,
            "verification": None,
            "execution": {"state": "may_execute", "confirmed_at": None, "basis": None},
        }
    )
    return _done(document, new, expected_revision)


def acknowledge(
    document: Document,
    conversation_id: str,
    direction: str,
    *,
    expected_revision: int,
    now: str,
    attempt_id: str,
    http_status: int = 200,
) -> Document:
    """Checkpoint an attributable positive result, including a tied late result."""
    new = _edit(document, expected_revision, now)
    rec = _record(new, conversation_id, direction)
    _require(rec["status"] in {"in_flight", "unknown"}, "no unresolved attempt")
    a = rec["attempts"][-1]
    _require(
        a["attempt_id"] == attempt_id and not a["acknowledged"],
        "wrong or acknowledged attempt",
    )
    a.update(acknowledged=True, http_status=http_status)
    if a["execution"]["state"] == "may_execute":
        a["execution"] = {
            "state": "quiescent",
            "confirmed_at": now,
            "basis": "request_completed",
        }
    return _done(document, new, expected_revision)


def record_outcome(
    document: Document,
    conversation_id: str,
    direction: str,
    *,
    expected_revision: int,
    now: str,
    attempt_id: str,
    outcome: str,
    error_code: str | None = None,
    http_status: int | None = None,
    verification_state: str | None = None,
    quiescent_basis: str | None = None,
) -> Document:
    """Record/reconcile evidence, never infer attribution from observations."""
    new = _edit(document, expected_revision, now)
    rec = _record(new, conversation_id, direction)
    _require(rec["status"] in {"in_flight", "unknown"}, "no unresolved attempt")
    a = rec["attempts"][-1]
    _require(a["attempt_id"] == attempt_id, "wrong attempt")
    _enum(outcome, {"succeeded", "failed", "unknown"})
    a["outcome"] = outcome
    if a["finished_at"] is None:
        a["finished_at"] = now
    if error_code is not None:
        a["error_code"] = error_code
    if http_status is not None:
        a["http_status"] = http_status
    if verification_state is not None:
        a["verification"] = {"checked_at": now, "state": verification_state}
    if quiescent_basis is not None and a["execution"]["state"] != "quiescent":
        a["execution"] = {
            "state": "quiescent",
            "confirmed_at": now,
            "basis": quiescent_basis,
        }
    rec.update(status=outcome, reason=a["error_code"])
    if outcome == "succeeded" and direction == "archive":
        _record(new, conversation_id, "undo")["status"] = "pending"
    return _done(document, new, expected_revision)


def skip(
    document: Document,
    conversation_id: str,
    direction: str,
    *,
    expected_revision: int,
    now: str,
    reason: str,
) -> Document:
    new = _edit(document, expected_revision, now)
    rec = _record(new, conversation_id, direction)
    rec.update(status="skipped", reason=reason)
    return _done(document, new, expected_revision)


def interrupted(
    document: Document,
    conversation_id: str,
    direction: str,
    *,
    expected_revision: int,
    now: str,
) -> Document:
    rec = _record(document, conversation_id, direction)
    _require(rec["status"] == "in_flight", "no interrupted intent")
    return record_outcome(
        document,
        conversation_id,
        direction,
        expected_revision=expected_revision,
        now=now,
        attempt_id=rec["attempts"][-1]["attempt_id"],
        outcome="unknown",
        error_code="interrupted",
    )


def holds(documents: Iterable[Document]) -> tuple[bool, frozenset[tuple[str, str]]]:
    """Return global execution hold and account/ID holds; in-flight is unknown."""
    global_hold = False
    ids: set[tuple[str, str]] = set()
    for document in documents:
        validate(document)
        for row in document["conversations"]:
            for direction in ("archive", "undo"):
                rec = row[direction]
                if rec["status"] in {"in_flight", "unknown"}:
                    ids.add((document["account_binding"], row["id"]))
                    global_hold |= (
                        rec["attempts"][-1]["execution"]["state"] == "may_execute"
                    )
    return global_hold, frozenset(ids)
