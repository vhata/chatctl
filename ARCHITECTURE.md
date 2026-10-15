# Architecture

What the structure is now, the boundaries parallel work must respect, and the invariants reviews check. The original brief is [docs/initial-plan.md](docs/initial-plan.md), designs ahead of the work are in [docs/specs/](docs/specs/) and plans in `plans/`; this file describes the code as it is.

## Layout

- `chatctl/cli.py`: the argparse command-line surface (`stats`, `archive`, `undo`). Parses and validates options; every command currently exits 1 with "not implemented yet".
- `chatctl/selection.py`: pure helpers that turn `--older-than` / `--before` into an archive cutoff.
- `chatctl/__main__.py`: `python -m chatctl` entry point; the `chatctl` console script is declared in `pyproject.toml`.
- `tests/`: pytest suites for the CLI and the selection helpers.
- `discovery/probe.js`: a read-only probe the user pastes into the DevTools console of a logged-in chatgpt.com tab. Outside a browser it exports its pure functions instead of running, which is how `discovery/probe.test.js` tests it with `node --test`.
- `docs/api-findings.md`: the recorded, dated behaviour of the undocumented ChatGPT endpoints, with evidence.

## Shared interfaces

- The CLI surface in `chatctl/cli.py` (command names, options, exit codes). The README and tests describe it; change all three together.
- `docs/api-findings.md` is the contract between discovery and client code: the client may only rely on behaviour recorded there (rule in [AGENTS.md](AGENTS.md#rules)).
- The archive manifest, once it exists, is the interface between `archive` and `undo`. Its format lands before either command depends on it.

## Invariants

- `chatctl/selection.py` reads no clock: the current time is passed in as a timezone-aware `now`. Callers in `cli.py` supply `datetime.now(UTC)`.
- Every network request in `discovery/probe.js` goes through `makeGet`, which issues GET requests only.
- The safety rules in [AGENTS.md](AGENTS.md#rules) (dry run without `--apply`, a fixed manifest before the first change, never touching project conversations, no account data in the repository) apply to all code; this file does not restate them.

## Isolation for concurrent work

Each worktree owns its mutable state: its own `.venv/` created by `bash scripts/setup.sh`, and `.pytest_cache/` and `.ruff_cache/`, all ignored by git. Nothing binds ports or writes outside the worktree. Hooks come from each worktree's own `.githooks/` because `core.hooksPath` is relative.

## Where to look first

- [AGENTS.md](AGENTS.md) for the rules, then [docs/api-findings.md](docs/api-findings.md) before touching anything that talks to ChatGPT.
- `chatctl/cli.py` for the command surface.
