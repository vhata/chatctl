# Deferred work

Ordinary follow-ups and bugs found during other work live here. Whole-codebase review findings promoted for separate work live in [review/BACKLOG.md](review/BACKLOG.md). Follow [docket/TODO_GUIDE.md](docket/TODO_GUIDE.md) before adding, claiming, moving or resolving an entry. Entries in **Ready for separate work** are unblocked and available now; an understood entry with an unresolved `Depends on:` or a `Blocked by:` goes in **Waiting** until it clears.

## Needs triage

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

- [TOOLING] `annotate-test-functions` — **Decide whether to annotate every test function and drop the mypy override for `tests/`.** The type-check gate checks test bodies but does not require test signatures to be annotated, which is the only relaxation of `--strict`.
  - Source: todo/choose-type-checker (#5), 2026-10-15

- [CLI] `exclude-starred-and-automation` — **Decide whether `archive` should skip starred conversations and scheduled-task conversations, and how.** The listing carries `is_starred` and `is_automation_conversation` (`docs/api-findings.md`, question 14), but no starred item and no star request has been observed, so a `--keep-starred` option would rest on a field nobody has seen set.
  - Source: triage of `docs/api-findings.md`, 2026-10-15
  - Starting point: the brief lists `--keep-starred` as a possible future option and says not to overbuild. Decide whether automation conversations should be skipped by default or only on request, then record it in `docs/DECISIONS.md`.

### Unprioritized

## Needs proof of concept

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

## Waiting

### P0 Critical

### P1 High

- [API] `patch-listing-disagreement` — **Find out why a conversation archived by a direct `PATCH` from the page appears in both listings, archived in one and not in the other, and stays in the sidebar.** Establish preflight and verification rules before either listing can drive archive or undo.
  - Source: user's minimal-PATCH test for `capture-archive-patch-headers`, 2026-10-24
  - Related: `archive-apply`, `undo-command`
  - Blocked by: the user running the [focused experiment](discovery/patch-listing-experiment.md) on the original throwaway and a UI control; agents must not access the account. Preparation and documentation reconciliation do not resolve the disagreement.
  - Evidence: the dated UI and wrapped-fetch observations, their limits and the archive/undo acceptance gates are recorded in [api-findings.md, question 13](docs/api-findings.md#13-does-changing-archive-state-immediately-remove-a-conversation-from-the-normal-history-endpoint).
  - Starting point: [listing_check.js](discovery/listing_check.js) scans both listings using local aliases. Recheck without mutation first, then compare UI archive/unarchive and actual outgoing header names. Preserve unknown outcomes; do not replay direct PATCHes to force agreement.

- [API] `test-minimal-archive-patch` — **Establish the actual request context needed for direct archive and unarchive through the intended transport.** One wrapped-fetch archive returned HTTP 200, but caller-only `Authorization` and `Content-Type` do not establish wire-header minimality or durable state (`docs/api-findings.md`, question 11).
  - Source: todo/choose-browser-transport (#7), 2026-10-24
  - Remaining from: `capture-archive-patch-headers`
  - Depends on: `patch-listing-disagreement`
  - Blocked by: user-captured actual wire-header evidence for the direct request and a verified direct unarchive result. Neither has been recorded; agents must not run these against the account.
  - Starting point: use the focused experiment's UI control and existing direct-request capture, if available, to choose a subsequent one-variable test. Do not guess additional headers or equate HTTP success with a verified archive.

### P2 Normal

- [CLI] `archive-manifest-format` — **Design and implement the archive manifest: what it records, where it is written, and how a partly applied run is resumed or undone.** It is the interface between `archive` and `undo` and must land before either depends on it (ARCHITECTURE.md).
  - Source: triage, 2026-10-15
  - Blocked by: the user's agreement on [the proposed design](docs/specs/2026-10-26-archive-manifest-format.md) before implementation.
  - Starting point: implement the agreed format as a pure module with private atomic storage, validation, transition helpers and tests. Archive/resume and undo command integration remain in their existing dependent tasks.
  - Per-conversation status needs an unknown state for requests whose outcome the transport could not report (see `archive-apply`). Source: #7, 2026-10-15.

- [CLI] `archive-apply` — **Make `chatctl archive --apply` write the manifest, then archive exactly the conversations in it, recording each result.** This is the mutation the tool exists for.
  - Source: triage, 2026-10-15
  - Depends on: `archive-manifest-format`, `test-minimal-archive-patch`, `patch-listing-disagreement`
  - Acceptance: the preflight and archive readback gates in [api-findings.md](docs/api-findings.md#mutation-gates) need evidence before implementation. A transport timeout, conflicting listings or incomplete readback stays unknown in the manifest; HTTP success alone cannot close it, and a PATCH must not be replayed. Source: #7 and user's direct-PATCH test, 2026-10-24.

- [CLI] `undo-command` — **Make `chatctl undo MANIFEST` unarchive exactly the conversations a manifest records as archived.** Undo is the other half of the safety principle.
  - Source: triage, 2026-10-15
  - Depends on: `archive-apply`, `archive-manifest-format`, `test-minimal-archive-patch`, `patch-listing-disagreement`
  - Acceptance: the restore and ownership gates in [api-findings.md](docs/api-findings.md#mutation-gates) require a verified direct unarchive and known pre-change state. Restore only changes confirmed as owned by this manifest; pre-existing archives and uncertain outcomes are not automatic undo candidates.

### P3 Low

### Unprioritized

## Ready for separate work

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized
