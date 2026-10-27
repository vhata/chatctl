import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chatctl import __version__, cli
from chatctl.cli import build_parser, main
from chatctl.transport import RemaldiTransport


def parse(*argv: str) -> argparse.Namespace:
    return build_parser().parse_args(list(argv))


def usage_error(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    with pytest.raises(SystemExit) as exc_info:
        parse(*argv)
    assert exc_info.value.code == 2
    return capsys.readouterr().err


def test_archive_older_than_defaults():
    args = parse("archive", "--older-than", "90d")
    assert args.command == "archive"
    assert args.older_than == timedelta(days=90)
    assert args.before is None
    assert args.exclude == []
    assert args.list is False
    assert args.apply is False


def test_archive_before():
    args = parse("archive", "--before", "2026-07-01", "--list", "--apply")
    assert args.before == datetime(2026, 7, 1, tzinfo=UTC)
    assert args.older_than is None
    assert args.list is True
    assert args.apply is True


def test_archive_exclude_is_repeatable_and_case_insensitive():
    args = parse(
        "archive", "--older-than", "90d", "--exclude", "discord", "--exclude", "home"
    )
    assert [pattern.pattern for pattern in args.exclude] == ["discord", "home"]
    assert args.exclude[0].search("Discord bot ideas")


def test_archive_requires_a_cutoff(capsys):
    err = usage_error(capsys, "archive")
    assert "one of the arguments --older-than --before is required" in err


def test_archive_cutoffs_are_mutually_exclusive(capsys):
    err = usage_error(
        capsys, "archive", "--older-than", "90d", "--before", "2026-07-01"
    )
    assert "not allowed with argument" in err


def test_archive_bad_duration_shows_reason(capsys):
    err = usage_error(capsys, "archive", "--older-than", "90x")
    assert "invalid duration '90x'" in err


def test_archive_huge_duration_is_a_usage_error(capsys):
    err = usage_error(capsys, "archive", "--older-than", "999999999999d")
    assert "too large" in err


def test_archive_bad_date_shows_reason(capsys):
    err = usage_error(capsys, "archive", "--before", "2026-7-1")
    assert "invalid date '2026-7-1'" in err


def test_archive_bad_regex_shows_reason(capsys):
    err = usage_error(capsys, "archive", "--older-than", "90d", "--exclude", "(")
    assert "invalid regex '('" in err


@pytest.mark.parametrize(
    "pattern", ["a{4294967295}", "a{1,4294967295}", "a{4294967295,}"]
)
def test_archive_oversized_regex_repetition_is_a_usage_error(pattern):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "chatctl",
            "archive",
            "--older-than",
            "90d",
            "--exclude",
            pattern,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage:" in result.stderr
    assert f"argument --exclude: invalid regex {pattern!r}" in result.stderr
    assert "Traceback" not in result.stderr


def test_undo_requires_manifest(capsys):
    err = usage_error(capsys, "undo")
    assert "MANIFEST" in err


def test_undo_parses_manifest_and_apply():
    args = parse("undo", "archive-run.json", "--apply")
    assert args.manifest == Path("archive-run.json")
    assert args.apply is True
    assert parse("undo", "archive-run.json").apply is False


def test_command_is_required(capsys):
    err = usage_error(capsys)
    assert "COMMAND" in err


def test_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        parse("--version")
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"chatctl {__version__}\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["archive", "--older-than", "90d"],
        ["archive", "--before", "2026-07-01", "--apply"],
        ["undo", "archive-run.json", "--apply"],
    ],
)
def test_commands_are_not_implemented(argv, capsys):
    assert main(argv) == 1
    assert capsys.readouterr().err == f"chatctl {argv[0]}: not implemented yet\n"


@pytest.mark.parametrize("duration", ["5000y", "999999999d"])
def test_archive_duration_reaching_before_year_one_is_a_usage_error(duration, capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["archive", "--older-than", duration])
    assert exc_info.value.code == 2
    assert "before year 1" in capsys.readouterr().err


def test_stats_requires_an_explicit_target(capsys):
    assert "--target" in usage_error(capsys, "stats")
    assert parse("stats", "--target", "placeholder-tab").target == "placeholder-tab"


@pytest.mark.parametrize("target", ["", " ", "--bad"])
def test_stats_rejects_invalid_targets_before_running_anything(
    target, monkeypatch, capsys
):
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid target must not start a transport")

    monkeypatch.setattr(cli, "RemaldiTransport", unexpected)
    with pytest.raises(SystemExit) as caught:
        main(["stats", f"--target={target}"])
    assert caught.value.code == 2
    assert "an explicit tab target is required" in capsys.readouterr().err


@pytest.mark.parametrize("option", ["--apply", "--before", "--older-than"])
def test_stats_rejects_mutation_and_selection_options(option, capsys):
    assert "unrecognized arguments" in usage_error(
        capsys, "stats", "--target", "tab", option
    )


def test_stats_fetches_both_scopes_sequentially_and_prints_aggregates(
    monkeypatch, capsys
):
    calls: list[Sequence[str]] = []
    clock_calls: list[bool] = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            clock_calls.append(True)
            return datetime(2026, 10, 26, 12, tzinfo=UTC)

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        # No partial output, even while the second listing is in progress.
        assert capsys.readouterr().out == ""
        calls.append(command)
        archived = "&is_archived=true" in command[-1]
        body = json.dumps(
            {
                "items": [
                    {
                        "id": "placeholder-id",
                        "title": "Placeholder title",
                        "gizmo_id": "g-p-placeholder" if archived else None,
                        "is_archived": archived,
                        "update_time": "2025-01-01T00:00:00Z",
                    }
                ],
                "offset": 0,
                "limit": 100,
                "total": 1,
            }
        )
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"result": {"value": {"ok": True, "body": body}}}),
            "",
        )

    def transport(target: str, *, archived: bool = False) -> RemaldiTransport:
        return RemaldiTransport(target, archived=archived, run=run)

    monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setattr(cli, "RemaldiTransport", transport)
    assert main(["stats", "--target", "placeholder-tab"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(calls) == 2 and len(clock_calls) == 1
    assert all(
        list(c[:4]) == ["remaldi", "evaluate", "--target", "placeholder-tab"]
        for c in calls
    )
    assert "&is_archived=true" not in calls[0][-1]
    assert "&is_archived=true" in calls[1][-1]
    assert "IDs present in both listings: 1" in captured.out
    assert "Default listing:" in captured.out and "Archived listing:" in captured.out
    assert "ordinary: 1" in captured.out and "project: 1" in captured.out
    assert "365+ days: 1" in captured.out
    assert "placeholder" not in captured.out and "Placeholder title" not in captured.out


@pytest.mark.parametrize("fail_on", [1, 2])
def test_stats_client_failure_prints_no_partial_or_sensitive_output(
    fail_on, monkeypatch, capsys
):
    calls: list[Sequence[str]] = []

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if len(calls) == fail_on:
            return subprocess.CompletedProcess(
                command, 1, "sensitive stdout", "sensitive stderr"
            )
        body = json.dumps({"items": [], "offset": 0, "limit": 100, "total": 0})
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"result": {"value": {"ok": True, "body": body}}}),
            "",
        )

    def transport(target: str, *, archived: bool = False) -> RemaldiTransport:
        return RemaldiTransport(target, archived=archived, run=run)

    monkeypatch.setattr(cli, "RemaldiTransport", transport)
    assert main(["stats", "--target", "tab"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "chatctl stats: remaldi_error\n"
    assert len(calls) == fail_on


def test_stats_empty_listings_are_successful(monkeypatch, capsys):
    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        body = '{"items": [], "offset": 0, "limit": 100, "total": 0}'
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"result": {"value": {"ok": True, "body": body}}}),
            "",
        )

    def transport(target: str, *, archived: bool = False) -> RemaldiTransport:
        return RemaldiTransport(target, archived=archived, run=run)

    monkeypatch.setattr(cli, "RemaldiTransport", transport)
    assert main(["stats", "--target", "tab"]) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and captured.out.count("Counted items: 0") == 2


def test_stats_interruption_has_no_partial_output(monkeypatch, capsys):
    def interrupted(target: str, *, archived: bool = False) -> RemaldiTransport:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "RemaldiTransport", interrupted)
    assert main(["stats", "--target", "tab"]) == 130
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "chatctl stats: interrupted\n"
