# Quality and validation

Read when changing code or preparing a PR. This document describes the gates as they exist now; history and rationale for past changes live in [DECISIONS.md](DECISIONS.md) and git.

## What quality means here

- Account safety above everything else: nothing touches a ChatGPT account without `--apply`, the mutation set is fixed in a manifest before the first change, and project and custom GPT conversations are never archived. The rules are in [AGENTS.md](../AGENTS.md#rules); tests and reviews hold code to them.
- Selection is exact and predictable: the cutoff and filters pick precisely the conversations the dry run shows, with no dependence on the wall clock inside the pure helpers.
- No account data in the repository: titles, full conversation IDs, tokens, probe reports, HAR files and manifests stay local.
- Deliberately manual: running the discovery probe and anything else against a real ChatGPT account. The user does that in their own browser session.

## Gates

Each check is a standalone script in `scripts/` or `docket/scripts/`, runnable from any directory, exiting non-zero on failure. Hooks, CI and agents run the same scripts.

| Script | Runs | Pre-commit | Pre-push | CI on PR | CI on main |
| --- | --- | --- | --- | --- | --- |
| `scripts/fmt-check.sh` | `ruff format --check` on Python files and the Python code blocks in Markdown files, excluding `docket/` | staged `.py` and `.md` files | yes | yes | yes |
| `scripts/lint.sh` | `ruff check`, rule set pinned in `pyproject.toml` | staged `.py` files | yes | yes | yes |
| `scripts/typecheck.sh` | mypy, strict, on `chatctl/` and `tests/`; configuration pinned in `pyproject.toml` | | yes | yes | yes |
| `scripts/test.sh` | pytest, then `node --test discovery/`; fails unless each suite passes at least one test | | yes | yes | yes |
| `scripts/smoke.sh` | the installed `chatctl` console script runs `--version` and `--help` | | | yes | yes |
| `docket/scripts/check-queues.sh` | queue format and dependencies in `TODO.md` and `review/BACKLOG.md` | staged queue files | `--strict` | via `ci.sh` | via `ci.sh` |
| `docket/scripts/check-links.sh` | relative Markdown links and anchors resolve | | yes | via `ci.sh` | via `ci.sh` |
| `docket/scripts/ci.sh` | queue hygiene, Markdown links, and on PRs the markers against the queues | | | yes | yes |
| `scripts/check.sh` | fmt-check, lint, typecheck, test, in order | | yes | yes | yes |

`scripts/check.sh` is the composite entry point: CI and the pre-push hook run it rather than the four gates individually. Test functions are exempt from mypy's annotation requirement, but their bodies are still checked; see [DECISIONS.md](DECISIONS.md#2026-10-15). `scripts/format.sh` is the write-mode counterpart of `fmt-check.sh` and also applies ruff's safe fixes.

Hooks are plain scripts in `.githooks/`, enabled by `git config core.hooksPath .githooks`, which `bash scripts/setup.sh` sets. Pre-commit only checks, never rewrites, and every check reads the staged content rather than the working copy. Pre-push runs `scripts/check.sh` and the queue and link validators against the working tree. Measured on this repository: pre-commit about 0.1 s with one Python file staged, pre-push about 1 to 1.5 s, both warm. Bypassing a hook (`--no-verify`) is for a broken toolchain only; state the bypass and the equivalent checks in the PR.

Toolchain pins: `.python-version` (3.12) and `uv.lock` for Python, `.nvmrc` (Node 26) for the probe's tests. uv itself is not pinned: CI installs the latest release, and `uv.lock` keeps the resolved dependencies identical. Bumping a pin is its own PR.

## Test policy

- Any change to selection, filtering, CLI parsing or exit codes adds or updates a pytest case in `tests/`.
- Any change to the pure parts of `discovery/probe.js` adds or updates a case in `discovery/probe.test.js`. Network behaviour is tested against a fake `fetch`; tests never reach chatgpt.com.
- Code that talks to ChatGPT is tested against recorded shapes from [api-findings.md](api-findings.md), never against a live account. Fixtures use placeholder titles and IDs.
- Documentation-only changes need no new tests; `docket/scripts/check-links.sh` covers their links.
- An empty or fully skipped suite is a failed gate: `scripts/test.sh` requires each suite to pass at least one test. There is no coverage threshold.
- No automatic retries. A flaky test is filed in `TODO.md` with its evidence and fixed or quarantined by name.

## Review inputs

Read by `docket/CODE_REVIEW_GUIDE.md`, which links this section by its heading, so keep the heading as it is; a codebase review runs and records exactly what is listed here.

- Focus areas: the correctness boundaries under [What quality means here](#what-quality-means-here) and the invariants in [ARCHITECTURE.md](../ARCHITECTURE.md#invariants). Above all, any path by which a conversation could be archived without `--apply`, outside the manifest, or while it belongs to a project or a custom GPT.
- Baseline commands beyond `bash scripts/check.sh`: `bash scripts/smoke.sh` (record pass or fail and the printed version).
- Drift checks for an incremental review: the CLI documented in `README.md` against `chatctl/cli.py`; claims in `docs/api-findings.md` against the code that depends on them; plan status in `plans/` against merged work; this document against `.githooks/` and `.github/workflows/ci.yml`; `noqa` and `type: ignore` counts.
- Source paths for `bash docket/scripts/review-due.sh --paths "chatctl tests discovery"`.
- Expected tracked files: `.py`, `.js`, `.md`, `.sh`, `.yml`, `.toml`, `uv.lock`, `LICENSE`, `.python-version`, `.nvmrc`, `.gitignore`, `docket/VERSION` and the hooks in `.githooks/`. Anything resembling a probe report, HAR file or manifest is a finding.

## CI

`.github/workflows/ci.yml` runs on pull requests and on pushes to `main`. Jobs: `check` (setup, `scripts/check.sh`, `scripts/smoke.sh`) and `Queue and PR hygiene` (`docket/scripts/ci.sh`). On pull requests the hygiene job's marker check compares the queues at the base branch tip with the checked-out merge commit. Superseded runs are cancelled on PR branches only, never on `main`. Nothing writes evidence files, so no artifacts are uploaded; the job log is the record.

## Scheduled validation of main

Not in use. Every check is fast enough for PR CI; see [DECISIONS.md](DECISIONS.md).

## Branch protection (as configured on 2026-10-15)

Configured as the repository ruleset "Protect main", active on the default branch. There is no classic branch protection.

- Required checks: `check` and `Queue and PR hygiene`, both from GitHub Actions; up-to-date-with-base: off. The push run on `main` catches the rare bad combination of two green PRs.
- Pull request required, squash the only allowed merge method, zero approving reviews; independent agent review is recorded in a review comment on each PR.
- Force pushes and deletion of `main`: blocked.
- Bypass: the repository admin role, always. That keeps direct-to-main commits of queue entries, plans and specs working (see [docket/CONTRACT.md](../docket/CONTRACT.md)) and lets the owner merge a red PR deliberately. Agents never use the bypass for anything else.
- Repository merge settings: squash only; squash title from the PR title and message from the PR body; head branches deleted on merge.

## PR evidence

Every PR lists the commands run and their results, a reproducible scenario for behaviour changes, what was not run and why, and the independent review. See [docket/CODE_REVIEW_GUIDE.md](../docket/CODE_REVIEW_GUIDE.md).
