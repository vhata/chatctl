# Review backlog

Only work promoted from whole-codebase reviews belongs here. Every entry is ready for separate work and carries a `Findings:` line naming the raw review findings it covers; each finding maps to at most one entry. Claiming and resolving follow [docket/TODO_GUIDE.md](../docket/TODO_GUIDE.md); promotion follows [docket/CODE_REVIEW_GUIDE.md](../docket/CODE_REVIEW_GUIDE.md).

## P0 Critical

## P1 High

## P2 Normal

## P3 Low

## Unprioritized

- [CLI] `handle-regex-overflow` — **Report oversized exclusion regex repetitions as usage errors.** An invalid repetition currently escapes argument validation as an uncaught `OverflowError`.
  - Source: [full review](2026-10-24-0247-full.md), 2026-10-24
  - Findings: `regex-repetition-overflow`
  - Starting point: `chatctl/cli.py:26` (`_regex`); handle regex repetition overflow and cover `--exclude 'a{4294967295}'` in CLI tests. It should exit 2 with an invalid-pattern message and no traceback.
