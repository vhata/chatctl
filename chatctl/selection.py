"""Pure helpers that decide which conversations an archive run selects.

``parse_duration``, ``parse_date`` and ``cutoff_from`` turn command-line
criteria into an archive cutoff. ``select_conversations`` applies that
cutoff, the safety rules in AGENTS.md and the ``--exclude`` patterns to
items from the conversation listing.

A conversation is selected for archiving when its ``update_time`` is
strictly earlier than the cutoff. Nothing here reads a clock or does I/O.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

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


class SkipReason(StrEnum):
    """Why a listing item was not selected.

    Members are listed in the order ``select_conversations`` checks them;
    ``CONFLICTING_DUPLICATE`` is applied afterwards (see there).
    """

    NOT_AN_OBJECT = "not-an-object"
    """The item is not a JSON object."""
    BAD_ID = "bad-id"
    """``id`` is missing, not a string, or empty."""
    DUPLICATE_ID = "duplicate-id"
    """An earlier item in the listing has the same ``id``."""
    GIZMO_ID_MISSING = "gizmo-id-missing"
    """``gizmo_id`` is absent, so project membership is unknown."""
    PROJECT_OR_CUSTOM_GPT = "project-or-custom-gpt"
    """``gizmo_id`` is present and not null."""
    ARCHIVED_STATE_UNKNOWN = "archived-state-unknown"
    """``is_archived`` is missing or not a boolean."""
    ALREADY_ARCHIVED = "already-archived"
    """``is_archived`` is true."""
    BAD_UPDATE_TIME = "bad-update-time"
    """``update_time`` is missing, not ISO 8601, or has no UTC offset."""
    BAD_TITLE = "bad-title"
    """``title`` is missing, or present but neither a string nor null."""
    TOO_RECENT = "too-recent"
    """``update_time`` is at or after the cutoff."""
    EXCLUDED = "excluded"
    """The title matches an exclude pattern."""
    CONFLICTING_DUPLICATE = "conflicting-duplicate"
    """A later copy of this conversation in the listing would be skipped."""


@dataclass(frozen=True, slots=True)
class Conversation:
    """A conversation selected for archiving."""

    id: str
    title: str | None
    update_time: datetime
    """The listing's ``update_time``, converted to UTC."""


@dataclass(frozen=True, slots=True)
class Skipped:
    """A listing item that was not selected, and why."""

    position: int
    """Zero-based index of the item in the input."""
    id: str | None
    """The item's ``id``, or None when it is missing or malformed."""
    title: str | None
    """The item's title when it is a string, otherwise None."""
    reason: SkipReason


@dataclass(frozen=True, slots=True)
class Selection:
    """The outcome of ``select_conversations``, each part in input order."""

    selected: tuple[Conversation, ...]
    skipped: tuple[Skipped, ...]


def select_conversations(
    items: Iterable[object],
    *,
    cutoff: datetime,
    exclude: Iterable[re.Pattern[str]] = (),
) -> Selection:
    """Split conversation listing items into selected and skipped.

    ``items`` are ``/backend-api/conversations`` listing items as decoded
    from JSON (docs/api-findings.md, questions 1, 4, 5, 6 and 13). An item
    is selected only when every check passes; otherwise it is skipped
    with the reason of the first check it fails. The checks run from the
    most safety-relevant to the least, so a project conversation is
    reported as one even when it is also too recent:

    1. ``NOT_AN_OBJECT``, ``BAD_ID``: the item is a mapping with a
       non-empty string ``id``.
    2. ``DUPLICATE_ID``: no earlier item had this ``id``.
    3. ``GIZMO_ID_MISSING``, ``PROJECT_OR_CUSTOM_GPT``: ``gizmo_id`` is
       present and null. A missing key is doubt, and doubt means skip.
    4. ``ARCHIVED_STATE_UNKNOWN``, ``ALREADY_ARCHIVED``: ``is_archived`` is
       exactly ``False``.
    5. ``BAD_UPDATE_TIME``: ``update_time`` is an ISO 8601 string with a
       UTC offset. A timestamp without one is skipped rather than given a
       guessed zone, since the API's format is recorded only as ISO 8601.
    6. ``BAD_TITLE``: ``title`` is present and is a string or null.
    7. ``TOO_RECENT``: ``update_time`` is strictly before ``cutoff``.
    8. ``EXCLUDED``: no pattern in ``exclude`` matches anywhere in the
       title (``re.search``). Patterns are used as compiled, so the CLI's
       ``re.IGNORECASE`` makes them case-insensitive. A null title has
       nothing to match and is not excluded. Age is checked first so that
       this reason counts only conversations a pattern kept back.

    The paged listing can shift between requests and return the same
    conversation twice. The first copy is the one evaluated and every
    later copy is skipped as ``DUPLICATE_ID``. If the first copy was
    selected but a later copy would have been skipped on its own (it now
    has a ``gizmo_id``, say), the first copy is withdrawn as
    ``CONFLICTING_DUPLICATE``: a conversation is selected only when every
    copy of it in the listing would be.

    The input is read once and never modified. Raises ``ValueError`` if
    ``cutoff`` is naive.
    """
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")
    patterns = tuple(exclude)
    outcomes: list[Conversation | Skipped] = []
    first_position: dict[str, int] = {}
    for position, item in enumerate(items):
        outcome = _check(position, item, cutoff, patterns)
        if outcome.id is None:
            outcomes.append(outcome)
            continue
        first = first_position.setdefault(outcome.id, position)
        if first == position:
            outcomes.append(outcome)
            continue
        earlier = outcomes[first]
        if isinstance(outcome, Skipped) and isinstance(earlier, Conversation):
            outcomes[first] = Skipped(
                first, earlier.id, earlier.title, SkipReason.CONFLICTING_DUPLICATE
            )
        outcomes.append(
            Skipped(position, outcome.id, outcome.title, SkipReason.DUPLICATE_ID)
        )
    return Selection(
        selected=tuple(o for o in outcomes if isinstance(o, Conversation)),
        skipped=tuple(o for o in outcomes if isinstance(o, Skipped)),
    )


def _check(
    position: int,
    item: object,
    cutoff: datetime,
    patterns: tuple[re.Pattern[str], ...],
) -> Conversation | Skipped:
    """Apply every check except the duplicate one to a single item."""
    if not isinstance(item, Mapping):
        return Skipped(position, None, None, SkipReason.NOT_AN_OBJECT)
    raw_title = item.get("title")
    title = raw_title if isinstance(raw_title, str) else None
    conversation_id = item.get("id")
    if not isinstance(conversation_id, str) or not conversation_id:
        return Skipped(position, None, title, SkipReason.BAD_ID)

    def skip(reason: SkipReason) -> Skipped:
        return Skipped(position, conversation_id, title, reason)

    if "gizmo_id" not in item:
        return skip(SkipReason.GIZMO_ID_MISSING)
    if item["gizmo_id"] is not None:
        return skip(SkipReason.PROJECT_OR_CUSTOM_GPT)
    is_archived = item.get("is_archived")
    if not isinstance(is_archived, bool):
        return skip(SkipReason.ARCHIVED_STATE_UNKNOWN)
    if is_archived:
        return skip(SkipReason.ALREADY_ARCHIVED)
    update_time = _parse_update_time(item.get("update_time"))
    if update_time is None:
        return skip(SkipReason.BAD_UPDATE_TIME)
    if "title" not in item or (raw_title is not None and title is None):
        return skip(SkipReason.BAD_TITLE)
    if update_time >= cutoff:
        return skip(SkipReason.TOO_RECENT)
    if title is not None and any(p.search(title) for p in patterns):
        return skip(SkipReason.EXCLUDED)
    return Conversation(conversation_id, title, update_time)


def _parse_update_time(value: object) -> datetime | None:
    """Parse an ISO 8601 timestamp with a UTC offset, as UTC; else None."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None
