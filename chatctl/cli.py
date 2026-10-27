"""Command-line interface for chatctl."""

import argparse
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from chatctl import __version__
from chatctl.selection import cutoff_from, parse_date, parse_duration


def _checked[T](parse: Callable[[str], T]) -> Callable[[str], T]:
    """Wrap a parser so argparse shows its ``ValueError`` message."""

    def convert(text: str) -> T:
        try:
            return parse(text)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from None

    return convert


def _regex(text: str) -> re.Pattern[str]:
    try:
        return re.compile(text, re.IGNORECASE)
    except (re.error, OverflowError) as exc:
        raise argparse.ArgumentTypeError(f"invalid regex {text!r}: {exc}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chatctl",
        description="Selectively archive old ChatGPT conversations.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    commands.add_parser("stats", help="summarise conversations (read-only)")

    archive = commands.add_parser(
        "archive", help="archive old conversations (dry run unless --apply)"
    )
    cutoff = archive.add_mutually_exclusive_group(required=True)
    cutoff.add_argument(
        "--older-than",
        metavar="DURATION",
        type=_checked(parse_duration),
        help="select conversations not updated within DURATION (90d, 2w, 6m, 1y)",
    )
    cutoff.add_argument(
        "--before",
        metavar="YYYY-MM-DD",
        type=_checked(parse_date),
        help="select conversations last updated before this date (UTC)",
    )
    archive.add_argument(
        "--exclude",
        metavar="REGEX",
        type=_regex,
        action="append",
        default=[],
        help="skip conversations whose title matches REGEX "
        "(case-insensitive, repeatable)",
    )
    archive.add_argument(
        "--list", action="store_true", help="print every selected conversation"
    )
    archive.add_argument(
        "--apply",
        action="store_true",
        help="actually archive; without this nothing is changed",
    )

    undo = commands.add_parser(
        "undo",
        help="unarchive the conversations listed in a manifest "
        "(dry run unless --apply)",
    )
    undo.add_argument(
        "manifest", metavar="MANIFEST", type=Path, help="manifest from an archive run"
    )
    undo.add_argument(
        "--apply",
        action="store_true",
        help="actually unarchive; without this nothing is changed",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "archive":
        try:
            cutoff_from(
                older_than=args.older_than, before=args.before, now=datetime.now(UTC)
            )
        except ValueError as exc:
            parser.error(str(exc))
    print(f"chatctl {args.command}: not implemented yet", file=sys.stderr)
    return 1
