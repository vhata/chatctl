"""Archive CLI integration through the real client and a fake remaldi runner."""

import json
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from chatctl import cli
from chatctl.client import ConversationClient, ListingTransport
from chatctl.selection import Selection, select_conversations
from chatctl.transport import RemaldiTransport


def item(identifier: str = "placeholder", **fields: object) -> dict[str, object]:
    return {
        "id": identifier,
        "title": f"Placeholder {identifier}",
        "gizmo_id": None,
        "is_archived": False,
        "update_time": "2025-01-01T00:00:00Z",
        **fields,
    }


def install_listing(
    monkeypatch: pytest.MonkeyPatch,
    pages: Sequence[Sequence[object]],
    *,
    fail_page: int | None = None,
    interrupt_page: int | None = None,
) -> list[Sequence[str]]:
    """Replace only the subprocess boundary; no real browser can be used."""
    calls: list[Sequence[str]] = []

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        page_index = len(calls)
        calls.append(command)
        assert list(command[:4]) == ["remaldi", "evaluate", "--target", "tab"]
        assert "&is_archived=true" not in command[-1]
        if page_index == interrupt_page:
            raise KeyboardInterrupt
        if page_index == fail_page:
            return subprocess.CompletedProcess(
                command, 1, "sensitive response title", "sensitive token"
            )
        offset = sum(len(page) for page in pages[:page_index])
        assert f"offset={offset}&limit=100" in command[-1]
        batch = pages[page_index]
        body = json.dumps(
            {
                "items": batch,
                "offset": offset,
                "limit": 100,
                "total": offset + len(batch) + (page_index < len(pages) - 1),
            }
        )
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"result": {"value": {"ok": True, "body": body}}}),
            "",
        )

    def transport(target: str) -> RemaldiTransport:
        return RemaldiTransport(target, run=run)

    def client(transport: ListingTransport) -> ConversationClient:
        return ConversationClient(transport, sleep=lambda _: None)

    monkeypatch.setattr(cli, "RemaldiTransport", transport)
    monkeypatch.setattr(cli, "ConversationClient", client)
    return calls


def test_archive_requires_explicit_target(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["archive", "--before", "2026-07-01"])
    assert caught.value.code == 2
    assert "--target" in capsys.readouterr().err


@pytest.mark.parametrize("target", ["", " ", "--bad"])
def test_archive_rejects_invalid_target_before_transport(target, monkeypatch, capsys):
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid target must not start a transport")

    monkeypatch.setattr(cli, "RemaldiTransport", unexpected)
    with pytest.raises(SystemExit) as caught:
        cli.main(["archive", f"--target={target}", "--before", "2026-07-01"])
    assert caught.value.code == 2
    assert "an explicit tab target is required" in capsys.readouterr().err


def test_archive_apply_is_unimplemented_before_transport(monkeypatch, capsys, tmp_path):
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("--apply must not start a transport")

    monkeypatch.setattr(cli, "RemaldiTransport", unexpected)
    monkeypatch.chdir(tmp_path)
    assert (
        cli.main(["archive", "--target", "tab", "--before", "2026-07-01", "--apply"])
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "chatctl archive: not implemented yet\n"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "criteria",
    [
        ["--older-than", "5000y"],
        ["--older-than", "90x"],
        ["--before", "2026-02-30"],
        ["--before", "2026-07-01", "--exclude", "("],
        ["--older-than", "90d", "--before", "2026-07-01"],
    ],
)
def test_archive_invalid_criteria_fail_before_transport(criteria, monkeypatch, capsys):
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid criteria must not start a transport")

    monkeypatch.setattr(cli, "RemaldiTransport", unexpected)
    with pytest.raises(SystemExit) as caught:
        cli.main(["archive", "--target", "tab", *criteria])
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and ": error:" in captured.err


def test_archive_reports_selection_exclusions_and_safety_skips(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.chdir(tmp_path)
    unknown = item("unknown")
    del unknown["gizmo_id"]
    calls = install_listing(
        monkeypatch,
        [
            [
                item("selected"),
                item("project", gizmo_id="g-p-placeholder"),
                item("custom", gizmo_id="g-placeholder"),
                unknown,
                item("recent", update_time="2026-07-01T00:00:00Z"),
                item("excluded", title="KEEP this"),
                item("also-excluded", title="Work notes"),
                item("untitled", title=None),
                item("archived", is_archived=True),
            ]
        ],
    )
    assert (
        cli.main(
            [
                "archive",
                "--target",
                "tab",
                "--before",
                "2026-07-01",
                "--exclude",
                "keep",
                "--exclude",
                "work",
                "--list",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == "" and len(calls) == 1
    assert "Selected: 2" in captured.out and "Skipped: 7" in captured.out
    for reason, count in [
        ("project-or-custom-gpt", 2),
        ("gizmo-id-missing", 1),
        ("too-recent", 1),
        ("excluded", 2),
        ("already-archived", 1),
    ]:
        assert f"{reason}: {count}" in captured.out
    assert "Placeholder selected" in captured.out and "untitled" in captured.out
    assert "Placeholder project" not in captured.out
    assert "KEEP this" not in captured.out and "Work notes" not in captured.out
    assert "DRY RUN" in captured.out
    assert list(tmp_path.iterdir()) == []


def test_archive_selects_once_after_all_pages_and_keeps_conflicting_duplicates(
    monkeypatch, capsys
):
    first_page = [item("conflict")] + [
        item(f"recent-{index}", update_time="2026-07-01T00:00:00Z")
        for index in range(99)
    ]
    calls = install_listing(
        monkeypatch, [first_page, [item("conflict", gizmo_id="g-p-placeholder")]]
    )
    selections: list[tuple[object, ...]] = []

    def select(items, *, cutoff, exclude) -> Selection:
        assert len(calls) == 2 and capsys.readouterr().out == ""
        selections.append(items)
        return select_conversations(items, cutoff=cutoff, exclude=exclude)

    monkeypatch.setattr(cli, "select_conversations", select)
    assert cli.main(["archive", "--target", "tab", "--before", "2026-07-01"]) == 0
    output = capsys.readouterr().out
    assert len(selections) == 1 and len(selections[0]) == 101
    assert "Selected: 0" in output and "Skipped: 101" in output
    assert "conflicting-duplicate: 1" in output and "duplicate-id: 1" in output
    assert "too-recent: 99" in output
    assert "Placeholder conflict" not in output


def test_archive_relative_cutoff_captures_now_once_before_listing(monkeypatch, capsys):
    clock_calls: list[bool] = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert calls == []
            clock_calls.append(True)
            assert tz is UTC
            return datetime(2026, 10, 26, 12, tzinfo=UTC)

    monkeypatch.setattr(cli, "datetime", Clock)
    calls = install_listing(
        monkeypatch,
        [
            [
                item("older", update_time="2026-07-28T11:59:59Z"),
                item("boundary", update_time="2026-07-28T12:00:00Z"),
            ]
        ],
    )
    assert cli.main(["archive", "--target", "tab", "--older-than", "90d"]) == 0
    output = capsys.readouterr().out
    assert clock_calls == [True]
    assert "2026-07-28T12:00:00+00:00" in output
    assert "Selected: 1" in output and "too-recent: 1" in output
    assert "Placeholder older" in output and "Placeholder boundary" not in output


@pytest.mark.parametrize("rows", [[], [item(update_time="2026-07-01T00:00:00Z")]])
def test_archive_empty_selection_succeeds(rows, monkeypatch, capsys):
    install_listing(monkeypatch, [rows])
    assert cli.main(["archive", "--target", "tab", "--before", "2026-07-01"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert (
        "Selected: 0" in captured.out and "No conversations selected." in captured.out
    )
    assert "DRY RUN" in captured.out and "Placeholder" not in captured.out


@pytest.mark.parametrize("fail_page", [0, 1])
def test_archive_failure_discards_partial_listing_and_sensitive_errors(
    fail_page, monkeypatch, capsys
):
    calls = install_listing(monkeypatch, [[item()], []], fail_page=fail_page)
    assert cli.main(["archive", "--target", "tab", "--before", "2026-07-01"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "chatctl archive: remaldi_error\n"
    assert len(calls) == fail_page + 1


@pytest.mark.parametrize("interrupt_page", [0, 1])
def test_archive_interruption_discards_partial_listing(
    interrupt_page, monkeypatch, capsys
):
    install_listing(monkeypatch, [[item()], []], interrupt_page=interrupt_page)
    assert cli.main(["archive", "--target", "tab", "--before", "2026-07-01"]) == 130
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "chatctl archive: interrupted\n"


def test_archive_help_explains_null_titles(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["archive", "--help"])
    assert caught.value.code == 0
    assert "a null title never matches" in " ".join(capsys.readouterr().out.split())
