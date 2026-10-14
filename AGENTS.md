# AGENTS.md

Working rules for this repository, for humans and coding agents alike.

<!-- docket:begin -->

## Docket

This project is run with docket. Read [docket/CONTRACT.md](docket/CONTRACT.md) before any work; it is the authoritative workflow, and this section records only this project's settings. The installer keeps this section current: the text above the list is rewritten on every run, the list keeps the values this project has set, and the section may sit anywhere in this file.

- Queue areas: `[CLI]` (chatctl commands, selection and output), `[API]` (the ChatGPT client and `docs/api-findings.md`), `[DISCOVERY]` (the probe kit in `discovery/`), `[TOOLING]`, `[DOCS]`.
- Concurrency cap: none for builds and tests, which are cheap. Anything that talks to ChatGPT runs one at a time; see the gentleness rule under Rules.
- Merging and releases: the user merges unless delegated in the turn. There are no releases; chatctl is not published.
- Optional pieces in force: review ledger (installed empty; the first codebase review is run on request) and stacked PRs when work needs them. Deferred: scheduled validation of main, until main has something too slow for PR CI; the roadmap queue, not in use.
- Environment: Python through uv only (see Environment below). The user runs the discovery probe and anything else that uses their logged-in ChatGPT session; agents prepare and review that code but never run it against a real account. Commits use the personal identity `jonathan.hitchcock@gmail.com` (set `git config user.email` in a fresh clone) and carry no AI attribution trailers or footers; credit lives in the README.

<!-- docket:end -->

## What this is

chatctl is a personal, local tool for selectively bulk-archiving old
ChatGPT conversations. [`README.md`](README.md) has the current status.
[`docs/initial-plan.md`](docs/initial-plan.md) is the original brief.
Design specs live in [`docs/specs/`](docs/specs/), implementation plans in
`plans/`, and the code's structure and invariants in
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Environment

- Python is managed with [uv](https://docs.astral.sh/uv/). Do not use `pip`
  or `python -m venv` directly.
- `bash scripts/setup.sh` runs `uv sync --locked`, which creates this
  worktree's `.venv/` with the package and dev tools, and installs the git
  hooks.
- Add runtime dependencies with `uv add` and tooling with `uv add --dev`.
  Commit `uv.lock`.
- Keep runtime dependencies at zero unless the standard library is clearly
  inadequate.

## Checks

Run `bash scripts/check.sh` before committing. It runs the formatter
check, ruff and both test suites (pytest and `node --test discovery/`).
CI runs it along with `scripts/smoke.sh` and `docket/scripts/ci.sh`.
[`docs/QUALITY.md`](docs/QUALITY.md) lists every gate and where it runs.

## Rules

- Nothing changes ChatGPT account state without an explicit `--apply`.
  Mutating commands are dry runs by default. A command that is not
  implemented must exit non-zero.
- The full mutation set is fixed and written to a manifest before the first
  change. Do not select conversations lazily while mutating.
- Never archive project conversations or custom GPT conversations: skip
  every conversation whose `gizmo_id` is non-null. If membership is
  ambiguous, skip the conversation.
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
