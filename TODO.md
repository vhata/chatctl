# Deferred work

Ordinary follow-ups and bugs found during other work live here. Whole-codebase review findings promoted for separate work live in [review/BACKLOG.md](review/BACKLOG.md). Follow [docket/TODO_GUIDE.md](docket/TODO_GUIDE.md) before adding, claiming, moving or resolving an entry. Entries in **Ready for separate work** are unblocked and available now; anything with an unresolved `Depends on:` belongs in an earlier stage.

## Needs triage

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

- [TOOLING] `choose-type-checker` — **Add a static type-check gate for `chatctl/` and `tests/`.** The code is fully annotated (including PEP 695 generics) but nothing checks the annotations, and `scripts/check.sh` has no typecheck step.
  - Source: docket adoption, branch vhata/docket-setup, 2026-10-14
  - Starting point: try mypy `--strict` and basedpyright against the current code, compare noise, then add `scripts/typecheck.sh` and the gate in `scripts/check.sh`, `.githooks/pre-push` (through check.sh) and `docs/QUALITY.md`.

## Needs proof of concept

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

- [API] `choose-browser-transport` — **Decide how chatctl's requests reach a logged-in browser session, and record it.** A plain HTTP client carrying only the token is stopped by Cloudflare's bot challenge (`docs/api-findings.md`, question 10), so the listing, archive and undo code has nothing to send requests through.
  - Source: vhata/probe-findings (#2), 2026-10-14
  - Starting point: the candidates are a console script pasted into the tab, browser automation of an authenticated profile, and evaluating JavaScript in an open chatgpt.com tab over the DevTools protocol, for example through the user's `remaldi evaluate --target <tab>` against Vivaldi started with `--remote-debugging-port`. On 2026-10-14 one read-only session and list request made that way returned 200 with the expected keys; that is a lead, not a recorded finding. A proof of concept should page the full listing that way, record the result in `docs/api-findings.md`, and add the choice to `docs/DECISIONS.md`.

## Ready for separate work

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized
