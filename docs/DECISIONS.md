# Decisions

Non-obvious choices and their trade-offs, dated, newest section first. Read the relevant entry before changing a mechanism that looks odd. Choices made autonomously under a delegation are recorded here for the user to review; an entry is a record, not a claim that the capability is complete.

## 2026-10-14

| Decision | Reason and trade-off |
| --- | --- |
| Git hooks are plain scripts in a tracked `.githooks/` directory, enabled by `git config core.hooksPath .githooks` in `scripts/setup.sh`. | No extra tool to install, locally or in CI. Lefthook or the `pre-commit` framework would add staged-file stashing and parallelism, which a repository this size does not need. Revisit if the hooks grow past a few checks. |
| The pre-commit hook only checks; it never rewrites files. It runs ruff against the staged blob of each staged Python file (`git show :path`), so unstaged edits neither hide nor cause failures. | A rewriting hook would need to restage files and could mix unstaged changes into the commit. `bash scripts/format.sh` is the explicit fix-up. |
| No type checker gate yet; `scripts/check.sh` runs fmt-check, lint and test only. | The code is annotated but has never been checked, and choosing between mypy and basedpyright (and how strict) is its own change. Queued in `TODO.md` as `choose-type-checker`. |
| `scripts/test.sh` fails when `node --test` collects no tests. | `node --test` exits 0 with zero tests, which would let a renamed or moved test file pass silently. pytest already exits 5 on empty collection. |
| Scheduled validation of main is deferred; there is no `main-validation.yml`. | Every check is fast enough to run on each PR and push, so a scheduled run would repeat PR CI. Add it when there is an expensive suite, or when the review ledger is in regular use and `review-due.sh` is worth scheduling. |
| Node is pinned in `.nvmrc` (major 26) for the probe's tests. | CI reads the pin from a file instead of a version typed into the workflow. The probe itself runs in whatever browser the user has; Node only runs its tests. |
| Design specs moved from `docs/superpowers/specs/` to `docs/specs/`; new plans go in `plans/`. The completed repo-skeleton plan was deleted rather than moved. | Docket's layout names directories after their content, not the tool that wrote them. Everything the plan described merged in #1 and git history keeps the plan. It quoted whole files, and docket's `check-links.sh` reads link syntax inside fenced code, so the quoted relative links failed the link check from their new location. |
| No branch protection on `main`. | GitHub does not offer branch protection or rulesets on private repositories under the current plan (the API returns 403). The rules bind agents through `AGENTS.md` and `docket/CONTRACT.md`; the repository's merge settings (squash only, PR title and body, delete branch on merge) are already in place. |
