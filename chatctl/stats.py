"""Pure aggregate summaries of listing observations, never account state."""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

KINDS = ("ordinary", "project", "custom GPT", "unknown")
ARCHIVE_STATES = ("unarchived", "archived", "unknown")
AGES = ("under 30 days", "30–89 days", "90–364 days", "365+ days", "future", "unknown")


@dataclass(frozen=True, slots=True)
class Summary:
    """Counts for one listing, collapsing repeated nonempty string IDs.

    Rows without a usable ID each count as an item, since their identity
    cannot be established. Duplicate IDs count once; conflicting category
    observations become unknown for that dimension. No raw item is retained.
    """

    rows: int
    total: int
    duplicates: int
    unidentified: int
    conflicts: int
    kinds: dict[str, int]
    archive_states: dict[str, int]
    ages: dict[str, int]
    ids: frozenset[str] = field(repr=False)


def _categories(item: object, now: datetime) -> tuple[str, str, str]:
    if not isinstance(item, Mapping):
        return ("unknown", "unknown", "unknown")
    kind = "unknown"
    if "gizmo_id" in item:
        gizmo = item["gizmo_id"]
        if gizmo is None and item.get("conversation_template_id") is None:
            kind = "ordinary"
        elif isinstance(gizmo, str):
            if gizmo.startswith("g-p-"):
                if len(gizmo) > 4:
                    kind = "project"
            elif gizmo.startswith("g-") and len(gizmo) > 2:
                kind = "custom GPT"
    state = item.get("is_archived")
    archive = (
        "archived" if state is True else "unarchived" if state is False else "unknown"
    )
    age = "unknown"
    raw_time = item.get("update_time")
    if isinstance(raw_time, str):
        try:
            updated = datetime.fromisoformat(raw_time)
            if updated.utcoffset() is not None:
                elapsed = now - updated.astimezone(UTC)
                if elapsed < timedelta(0):
                    age = "future"
                elif elapsed < timedelta(days=30):
                    age = AGES[0]
                elif elapsed < timedelta(days=90):
                    age = AGES[1]
                elif elapsed < timedelta(days=365):
                    age = AGES[2]
                else:
                    age = AGES[3]
        except (ValueError, OverflowError):
            pass
    return kind, archive, age


def summarise(items: Iterable[object], *, now: datetime) -> Summary:
    """Summarise a completed listing using one supplied, aware clock value.

    Kind uses the observed gizmo prefixes, not a membership guarantee. Age
    means elapsed time since update_time. Nothing here performs I/O, reads
    a clock, changes its input or chooses an authoritative duplicate copy.
    """
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)
    groups: dict[str, list[tuple[str, str, str]]] = {}
    categories: list[tuple[str, str, str]] = []
    rows = 0
    for item in items:
        rows += 1
        values = _categories(item, now)
        identifier = item.get("id") if isinstance(item, Mapping) else None
        if isinstance(identifier, str) and identifier.strip():
            groups.setdefault(identifier, []).append(values)
        else:
            categories.append(values)
    unidentified = len(categories)
    conflicts = 0
    for copies in groups.values():
        dimensions = [set(values) for values in zip(*copies, strict=True)]
        if any(len(values) > 1 for values in dimensions):
            conflicts += 1
        merged = [
            next(iter(values)) if len(values) == 1 else "unknown"
            for values in dimensions
        ]
        categories.append((merged[0], merged[1], merged[2]))
    counts = (
        [Counter(values) for values in zip(*categories, strict=True)]
        if categories
        else [Counter(), Counter(), Counter()]
    )
    return Summary(
        rows=rows,
        total=len(categories),
        duplicates=rows - unidentified - len(groups),
        unidentified=unidentified,
        conflicts=conflicts,
        kinds={key: counts[0][key] for key in KINDS},
        archive_states={key: counts[1][key] for key in ARCHIVE_STATES},
        ages={key: counts[2][key] for key in AGES},
        ids=frozenset(groups),
    )


def render_stats(default: Summary, archived: Summary) -> str:
    """Render aggregate counts only, with no conversation identifiers."""
    lines = [
        "Listing observations (read-only; not an authoritative account snapshot).",
        "The default and archived listings can disagree; their counts are separate.",
        f"IDs present in both listings: {len(default.ids & archived.ids)}",
    ]
    for label, summary in (
        ("Default listing", default),
        ("Archived listing", archived),
    ):
        lines.extend(
            [
                "",
                f"{label}:",
                f"  Rows received: {summary.rows}",
                f"  Counted items: {summary.total}",
                f"  Repeated ID rows: {summary.duplicates}",
                f"  IDs with conflicting categories: {summary.conflicts}",
                f"  Rows without usable ID: {summary.unidentified}",
            ]
        )
        for heading, counts in (
            ("Kind (observed gizmo_id prefixes)", summary.kinds),
            ("Archive state (reported is_archived)", summary.archive_states),
            ("Age (since update_time)", summary.ages),
        ):
            lines.append(f"  {heading}:")
            lines.extend(
                f"    {category}: {count}" for category, count in counts.items()
            )
    return "\n".join(lines)
