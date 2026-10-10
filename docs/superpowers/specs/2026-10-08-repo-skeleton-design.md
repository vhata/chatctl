# chatctl: repository skeleton and discovery kit

Date: 2026-10-08
Status: approved

## Context

`docs/initial-plan.md` (currently `initial-plan.md` at the repo root)
describes a local tool for selectively bulk-archiving old ChatGPT
conversations. Everything it does depends on undocumented
`/backend-api/...` endpoints, and the plan requires those to be
investigated before anything is built on them.

This first pass does two things:

1. Gives the repository a working Python skeleton that later phases plug
   into.
2. Provides a read-only discovery kit so the user can answer the plan's
   open API questions from their own logged-in browser session.

The tool is named **chatctl** (package `chatctl`, console script
`chatctl`), replacing `chatgpt-archive` / `chatgpt_archiver` from the
initial plan.

## Out of scope

- Any Python HTTP client or API code.
- Any mutation code (archive, unarchive) in Python or JavaScript.
- Data models for conversations; their shape depends on discovery.
- Manifest reading or writing.

## 1. Python skeleton

### Environment

- Managed with `uv`. No direct use of `pip` or `python -m venv`.
- `.python-version` pins `3.12`.
- `uv sync` creates the project-local virtualenv at `.venv/` and
  installs the package (editable) plus the `dev` dependency group.
- `uv.lock` is committed. `.venv/` is gitignored.
- Commands run through uv: `uv run pytest`, `uv run ruff check .`,
  `uv run chatctl ...`.

### Packaging

- `pyproject.toml`, build backend `hatchling`, `requires-python = ">=3.12"`.
- No runtime dependencies.
- Dev tools in a PEP 735 `[dependency-groups]` `dev` group (added with
  `uv add --dev`): `pytest`, `ruff`.
- Console script: `chatctl = "chatctl.cli:main"`.
- Ruff configured in `pyproject.toml` with defaults plus import sorting.

### Layout

```text
chatctl/
    __init__.py      # __version__
    __main__.py      # python -m chatctl
    cli.py           # argparse definition and dispatch
    selection.py     # pure cutoff / duration logic
tests/
    test_cli.py
    test_selection.py
```

`api.py`, `models.py` and `manifest.py` from the initial plan are not
created until they have content.

### CLI

`chatctl` uses `argparse` with three subcommands. Argument parsing and
validation are real; each command then prints
`chatctl <command>: not implemented yet` to stderr and exits with
status 1.

- `chatctl stats` takes no options.
- `chatctl archive`
  - Exactly one of `--older-than DURATION` or `--before YYYY-MM-DD` is
    required (mutually exclusive group).
  - `--exclude REGEX`, repeatable. Each pattern is compiled at parse
    time with `re.IGNORECASE`; an invalid pattern is a usage error.
  - `--list` prints every selected conversation (flag only for now).
  - `--apply` performs the mutation. Without it the command is a dry run.
- `chatctl undo MANIFEST`
  - `MANIFEST` is a path. It is not opened in this phase.
  - `--apply`, same meaning as for `archive`. Undo is also dry-run by
    default, which differs from the initial plan's example and is
    deliberate.
- `chatctl --version` prints the version.

`main(argv: list[str] | None = None) -> int` is the entry point so that
tests can call it directly.

### selection.py

Pure functions with no I/O:

- `parse_duration(text: str) -> datetime.timedelta`
  - Format: a positive integer followed by one unit: `d` (days),
    `w` (weeks), `m` (months, fixed at 30 days), `y` (years, fixed at
    365 days). Examples: `90d`, `2w`, `6m`, `1y`.
  - Fixed-length months and years are deliberate. Calendar arithmetic
    adds code for no practical benefit when choosing archive cutoffs.
  - Zero, negative, missing-unit, unknown-unit and whitespace-padded
    inputs raise `ValueError`.
- `parse_date(text: str) -> datetime.datetime`
  - Accepts `YYYY-MM-DD` only and returns midnight UTC on that date
    (timezone-aware). Anything else raises `ValueError`.
- `cutoff_from(*, older_than: timedelta | None, before: datetime | None, now: datetime) -> datetime`
  - Returns `now - older_than` or `before`. Exactly one argument must be
    set, otherwise `ValueError`. `now` is a parameter so that tests are
    deterministic.
- Selection semantics, recorded for later phases: a conversation is
  selected when its `update_time` is strictly earlier than the cutoff.

The CLI uses `parse_duration` and `parse_date` as argparse `type=`
callables, so bad values show up as normal usage errors.

### Tests

- `test_selection.py` covers each unit, rejection of malformed
  durations and dates, the UTC midnight result of `parse_date`, and
  `cutoff_from` with both arguments, neither argument and each one on
  its own.
- `test_cli.py` covers the required/mutually exclusive cutoff options,
  bad duration, bad date, invalid regex, `undo` requiring a path,
  `--version`, and the "not implemented" exit status for each command.

## 2. Discovery kit

### discovery/probe.js

A snippet pasted into the DevTools console of a logged-in
`https://chatgpt.com` tab.

**Read-only by construction.** All network access goes through one
`get(path)` helper. It takes only a path, calls `fetch` with a
hard-coded `method: "GET"` and no body, and no other code calls
`fetch`.

**Authentication.** It reads the access token from
`GET /api/auth/session`, the same way the web app does, and holds it in
a local variable only. The token is never logged, printed or included
in the report.

**Probes.** Each probe records the HTTP status, top-level response keys
and a structural summary. A failing probe is recorded and does not stop
the others.

1. The session response: top-level keys only, with values redacted.
2. The conversation list, paginated:
   `/backend-api/conversations?offset=N&limit=L&order=updated`, with a
   500 ms delay between requests and a hard cap of 200 pages. The first
   request uses `limit=100`; `L` for later pages is the `limit` the
   server reports back, or the number of items actually returned if it
   reports none. `offset` advances by the number of items received.
   The walk stops on an empty page, or when a reported `total` has been
   reached. It records the pagination fields returned (for example
   `total`, `limit`, `offset`, `has_missing_conversations`), the
   requested and effective page size, and the count of items
   collected.
3. Archived listing: the same endpoint with `is_archived=true`, first
   page only.
4. Project discovery: `GET /backend-api/gizmos/snorlax/sidebar` (the
   endpoint the sidebar is believed to use for projects), first page
   only. Its structure is summarised; it is not paginated further.

These paths are hypotheses. The discovery README tells the user to
compare them against the Network tab and edit the `ENDPOINTS` constant
at the top of the script if they differ.

**Structural summary.** For list items, it records:

- Every field name seen, with its JavaScript type(s) and how often it
  appears.
- For fields whose name contains `time` or ends in `_at`, the value
  format (ISO 8601 string, epoch seconds or milliseconds, or other),
  not the value itself.
- For fields that may indicate project membership (any key containing
  `gizmo`, `project`, `workspace` or `snorlax`), the distribution of
  distinct values. Values of ID-named keys (ending in `id`) are truncated
  to 8 characters; other values are reduced to type and length, since
  they could be user-chosen names. (Amended after final review.)
- `title` replaced by its length; `id` truncated to its first 8
  characters.

**Aggregates.** Count of conversations by month of `update_time` and by
month of `create_time`, plus counts older than 30, 60, 90, 180 and 365
days by `update_time`.

**Output.** The report is a JSON object. It is downloaded via a Blob
link as `chatctl-probe-<UTC timestamp>.json` and a short summary is
logged to the console. Nothing is sent anywhere else.

### discovery/README.md

- How to run the probe: open chatgpt.com, open DevTools, paste
  `probe.js`, wait, collect the download.
- A Network tab checklist for what a GET probe cannot show:
  - Archive one throwaway conversation by hand and record the method,
    path, request body, response and relevant request headers (with the
    authorization value redacted).
  - Unarchive it from Settings and record the same.
  - Open a project and record the requests that list its conversations.
  - Note whether archiving removes the conversation from the normal
    list straight away.
  - Note any CSRF or origin-related headers the UI sends.
- A reminder that the probe output and any HAR files contain account
  metadata and are gitignored.

### docs/api-findings.md

The 14 open questions from the initial plan, each with an empty
"Finding" and "Evidence" slot, plus a short section recording the date
and how the findings were gathered.

### Verification

- `node --check discovery/probe.js` passes.
- The probe only works for real when the user runs it in their
  browser; that is the acceptance test for this part.

## 3. Docs and repo hygiene

- Move `initial-plan.md` to `docs/initial-plan.md` and add a note at
  the top that the tool has been renamed to `chatctl`.
- `README.md`: what chatctl is, current status (skeleton plus
  discovery, no archiving yet), the safety principle quoted from the
  plan, setup and test commands (uv), a pointer to `discovery/`, and a
  one-line credit that the project was built with Claude.
- `AGENTS.md`: uv setup (`uv sync`, `uv run ...`), how to run tests and lint, the rule
  that nothing mutates account state without an explicit `--apply`,
  the rule that the discovery probe stays GET-only, and the privacy
  rules (no titles, IDs or tokens in committed files).
- `CLAUDE.md`: a single line pointing to `AGENTS.md`.
- `.gitignore`: `.venv/`, Python caches and build artefacts,
  `chatctl-probe-*.json`, `*.har`, `archive-run-*.json` and
  `archive-run-*.failures.json`.

## Done when

- `uv run pytest` passes.
- `uv run ruff check .` and `uv run ruff format --check .` pass.
- `uv run chatctl --version` and `uv run chatctl archive --older-than 90d`
  behave as described above.
- `node --check discovery/probe.js` passes.
