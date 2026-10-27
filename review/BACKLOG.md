# Review backlog

Only work promoted from whole-codebase reviews belongs here. Every entry is ready for separate work and carries a `Findings:` line naming the raw review findings it covers; each finding maps to at most one entry. Claiming and resolving follow [docket/TODO_GUIDE.md](../docket/TODO_GUIDE.md); promotion follows [docket/CODE_REVIEW_GUIDE.md](../docket/CODE_REVIEW_GUIDE.md).

## P0 Critical

## P1 High

## P2 Normal

## P3 Low

## Unprioritized

- [CLI] `handle-regex-recursion` — **Report deeply nested exclusion patterns as usage errors.** Regex compilation can exceed Python's recursion limit, producing an uncaught traceback instead of an argparse diagnostic.
  - Source: [2026-10-27 full review](2026-10-27-1619-full.md), 2026-10-27
  - Findings: `regex-nesting-recursion`
  - Starting point: handle `RecursionError` in `chatctl/cli.py` (`_regex`) alongside the existing compiler errors; test a 500-group nested pattern, exit 2 with usage text, no traceback and no transport calls.
