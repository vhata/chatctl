from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chatctl import __version__
from chatctl.cli import build_parser, main


def parse(*argv):
    return build_parser().parse_args(list(argv))


def usage_error(capsys, *argv):
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
        ["stats"],
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
