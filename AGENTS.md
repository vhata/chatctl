# AGENTS.md

Working rules for this repository, for humans and coding agents alike.

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
