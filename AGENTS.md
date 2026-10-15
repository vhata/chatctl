# AGENTS.md

Working rules for this repository, for humans and coding agents alike.

<!-- docket:begin -->

## Docket

This project is run with docket. Read [docket/CONTRACT.md](docket/CONTRACT.md) before any work; it is the authoritative workflow, and this section records only this project's settings. The installer keeps this section current: the text above the list is rewritten on every run, the list keeps the values this project has set, and the section may sit anywhere in this file.

- Queue areas: <`[AREA]`, `[AREA]`, `[TOOLING]`, `[DOCS]`>.
- Concurrency cap: <N heavy builds or runs at once | none>.
- Merging and releases: <the user merges unless delegated in the turn | standing delegation>.
- Optional pieces in force: <review ledger | roadmap queue | stacked PRs | scheduled validation of main | all | none>; name what is in force and what is deferred.
- Environment: <rules such as "the user runs the dev server">.

<!-- docket:end -->

## What this is

chatctl is a personal, local tool for selectively bulk-archiving old
ChatGPT conversations. [`README.md`](README.md) has the current status.
[`docs/initial-plan.md`](docs/initial-plan.md) is the original brief, and
[`docs/superpowers/`](docs/superpowers/) holds design specs and
implementation plans.

## Environment

- Python is managed with [uv](https://docs.astral.sh/uv/). Do not use `pip`
  or `python -m venv` directly.
- `uv sync` creates `.venv/` and installs the package and dev tools.
- Add runtime dependencies with `uv add` and tooling with `uv add --dev`.
  Commit `uv.lock`.
- Keep runtime dependencies at zero unless the standard library is clearly
  inadequate.

## Checks

Run all of these before committing:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
node --test discovery/
```

## Rules

- Nothing changes ChatGPT account state without an explicit `--apply`.
  Mutating commands are dry runs by default. A command that is not
  implemented must exit non-zero.
- The full mutation set is fixed and written to a manifest before the first
  change. Do not select conversations lazily while mutating.
- Never archive project conversations. If project membership is ambiguous,
  skip the conversation.
- `discovery/probe.js` is GET-only. All of its requests go through
  `makeGet`. Do not add other network calls.
- Code may only depend on undocumented ChatGPT endpoints once their
  behaviour is recorded, with evidence, in
  [`docs/api-findings.md`](docs/api-findings.md).
- Never commit conversation titles, full conversation IDs, access tokens,
  probe reports, HAR files or archive manifests. `.gitignore` covers the
  usual filenames; check any new data file before adding it.
- Keep requests to ChatGPT gentle: one at a time or very low concurrency,
  with bounded retries and backoff on 429 and 5xx.
