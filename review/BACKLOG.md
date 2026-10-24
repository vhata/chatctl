# Review backlog

Only work promoted from whole-codebase reviews belongs here. Every entry is ready for separate work and carries a `Findings:` line naming the raw review findings it covers; each finding maps to at most one entry. Claiming and resolving follow [docket/TODO_GUIDE.md](../docket/TODO_GUIDE.md); promotion follows [docket/CODE_REVIEW_GUIDE.md](../docket/CODE_REVIEW_GUIDE.md).

## P0 Critical

## P1 High

## P2 Normal

## P3 Low

## Unprioritized

- [DISCOVERY] `redact-probe-errors` — **Keep exception messages out of probe reports.** The projects error path currently bypasses the report's privacy boundary.
  - Source: [full review](2026-10-24-0247-full.md), 2026-10-24
  - Findings: `probe-exception-text-disclosure`
  - Starting point: `discovery/probe.js:359` (`runProbe`); use the error-type-only treatment already in `walkList` and add a fake-fetch privacy regression for a rejected projects request. The reproduction is synthetic, with no observed native-browser credential disclosure.

- [CLI] `handle-regex-overflow` — **Report oversized exclusion regex repetitions as usage errors.** An invalid repetition currently escapes argument validation as an uncaught `OverflowError`.
  - Source: [full review](2026-10-24-0247-full.md), 2026-10-24
  - Findings: `regex-repetition-overflow`
  - Starting point: `chatctl/cli.py:26` (`_regex`); handle regex repetition overflow and cover `--exclude 'a{4294967295}'` in CLI tests. It should exit 2 with an invalid-pattern message and no traceback.

- [TOOLING] `reject-empty-node-tests` — **Reject JavaScript test files containing no test declarations.** Node's passing file wrapper currently satisfies the required test gate even when every discovery test has been removed.
  - Source: [full review](2026-10-24-0247-full.md), 2026-10-24
  - Findings: `node-empty-file-counts-as-test`
  - Starting point: `scripts/test.sh:45`; distinguish actual passing test cases from an empty file's wrapper success. In a disposable fixture with one passing pytest test and an import-only `discovery/probe.test.js`, the script must fail rather than accept Node's `# pass 1` summary.
