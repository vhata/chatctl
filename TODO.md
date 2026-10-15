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

## Ready for separate work

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized
