"""Pure, terminal-safe output for an archive dry run."""

import json
from collections import Counter
from datetime import UTC, datetime

from chatctl.selection import Conversation, Selection, SkipReason


def _conversation_row(conversation: Conversation) -> str:
    """Render selector-validated IDs and UTC times with JSON-escaped titles."""
    updated = conversation.update_time.astimezone(UTC).isoformat()
    title = json.dumps(conversation.title, ensure_ascii=True)
    return f"{updated}  {conversation.id}  {title}"


def render_archive(
    selection: Selection, *, cutoff: datetime, list_all: bool = False
) -> str:
    """Describe a completed selection without I/O, selection or a clock.

    Counts describe listing rows, including duplicates, rather than an
    authoritative account total. Selected rows come from selection.py,
    which has already validated IDs and timestamp offsets. JSON quoting
    keeps untrusted titles on one ASCII-safe terminal line; null stays
    distinguishable from every literal title.
    """
    if cutoff.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")
    selected = selection.selected
    skipped = selection.skipped
    lines = [
        "DRY RUN: no conversations modified.",
        "Cutoff (UTC; update_time strictly before): "
        + cutoff.astimezone(UTC).isoformat(),
        "Default listing rows received: "
        f"{len(selected) + len(skipped)} (including duplicate rows).",
        f"Selected: {len(selected)}",
        f"Skipped: {len(skipped)}",
        "Skip reasons:",
    ]
    reasons = Counter(item.reason for item in skipped)
    lines.extend(
        f"  {reason.value}: {reasons[reason]}"
        for reason in SkipReason
        if reasons[reason]
    )
    if not skipped:
        lines.append("  none")
    lines.append("Listing observations are not an authoritative account snapshot.")
    if not selected:
        lines.append("No conversations selected.")
    elif list_all:
        lines.append("Selected conversations (listing order):")
        lines.extend(f"  {_conversation_row(item)}" for item in selected)
    elif len(selected) == 1:
        lines.append(f"Oldest/newest selected: {_conversation_row(selected[0])}")
    else:
        oldest = min(selected, key=lambda item: item.update_time)
        newest = max(reversed(selected), key=lambda item: item.update_time)
        lines.extend(
            [
                f"Oldest selected: {_conversation_row(oldest)}",
                f"Newest selected: {_conversation_row(newest)}",
            ]
        )
    return "\n".join(lines)
