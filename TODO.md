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

- [API] `choose-browser-transport` — **Decide how chatctl's requests reach a logged-in browser session, and record it.** A plain HTTP client carrying only the token is stopped by Cloudflare's bot challenge (`docs/api-findings.md`, question 10), so the listing, archive and undo code has nothing to send requests through.
  - Source: vhata/probe-findings (#2), 2026-10-14
  - Starting point: the candidates are a console script pasted into the tab, browser automation of an authenticated profile, and evaluating JavaScript in an open chatgpt.com tab over the DevTools protocol, for example through the user's `remaldi evaluate --target <tab> --await-promise --return-by-value` against Vivaldi started with `--remote-debugging-port`. On 2026-10-14 one read-only session and list request made that way returned 200 with the expected keys; that is a lead, not a recorded finding. A proof of concept should page the full listing that way, record the result in `docs/api-findings.md`, and add the choice to `docs/DECISIONS.md`. Agents can write the proof of concept; the user runs it.

### P2 Normal

### P3 Low

### Unprioritized

## Waiting

### P0 Critical

### P1 High

- [API] `record-field-shapes` — **Record in `docs/api-findings.md` whether `update_time` and `create_time` carry a UTC offset (and fractional seconds), and whether `title` can be null or missing.** Question 4 says only "ISO 8601" because the probe classifies timestamps by their date prefix, and the selection rules skip any timestamp without an offset, so an offset-free API would select nothing.
  - Source: todo/select-conversations (#6), 2026-10-15
  - Depends on: `choose-browser-transport`
  - Related: `archive-dry-run`
  - Starting point: the transport proof of concept counts these shapes (never values); record its output under questions 4 and 1. Selection fails safe either way, so this decides whether `archive-dry-run` can select anything, not whether it is safe.
  - The decision record should state the cost of the transport, for example that while a DevTools port is open any local process can control the whole browser. Source: review of #7, 2026-10-15.
  - Also record whether `conversation_template_id` and `gizmo_id` are non-null on the same items; selection skips a non-null `conversation_template_id` until this is known (#6). The proof of concept in #7 counts the co-occurrence.
  - The `--exclude` help should say that a conversation with a null title never matches a pattern. Source: review of #6, 2026-10-15.

- [API] `capture-archive-patch-headers` — **Record the names of the headers the web UI sends with its archive `PATCH`, and whether a `PATCH` carrying only `Authorization` is accepted.** Question 11 in `docs/api-findings.md` is open on this, and no code may send a `PATCH` until it is answered.
  - Source: triage of `docs/api-findings.md`, 2026-10-15
  - Blocked by: the user capturing an archive and an unarchive of a throwaway conversation in the browser's Network tab (header names only, never values).
  - Starting point: record the header names under question 11, dated, with evidence; note any sentinel, device or CSRF header that the client would have to reproduce.

- [API] `conversation-client` — **Page the full conversation listing through the chosen transport.** Every command needs the listing, and its pagination has a misleading `total` (`docs/api-findings.md`, question 2).
  - Source: triage of `docs/api-findings.md`, 2026-10-15
  - Depends on: `choose-browser-transport`
  - Starting point: offset/limit paging with `limit=100`, stopping at `offset + len(items) >= total` or an empty page; requests one at a time with bounded retries and backoff on 429 and 5xx (AGENTS.md rules). Test against fixtures shaped like the recorded responses, behind a fake transport.
  - Decode responses rejecting duplicate JSON keys (`object_pairs_hook`): `json.loads` keeps the last duplicate, so a doubled `gizmo_id` could read as null. Source: review of #6, 2026-10-15.
  - Percent-encode ids in request paths (`quote(id, safe="")`) even though selection restricts their characters. Source: review of #6, 2026-10-15.
  - With remaldi, always pass an explicit `--target` and check `location.origin` in the page: remaldi's default target is Vivaldi's privileged UI page. Decide whether fetching the session on every page (two GETs per page in the proof of concept) is acceptable or how to reuse the token without it leaving the page. Source: #7, 2026-10-15.

### P2 Normal

- [CLI] `stats-command` — **Make `chatctl stats` summarise the listing: counts by kind (ordinary, project, custom GPT), archived state and age.** A read-only command is the first end-to-end use of the client and the safest one.
  - Source: triage, 2026-10-15
  - Depends on: `conversation-client`

- [CLI] `archive-dry-run` — **Make `chatctl archive` without `--apply` list the selection and its summary against the live listing.** This is the brief's first workflow, and it changes nothing.
  - Source: triage, 2026-10-15
  - Depends on: `conversation-client`, `select-conversations`

- [CLI] `archive-apply` — **Make `chatctl archive --apply` write the manifest, then archive exactly the conversations in it, recording each result.** This is the mutation the tool exists for.
  - Source: triage, 2026-10-15
  - Depends on: `archive-dry-run`, `archive-manifest-format`, `capture-archive-patch-headers`
  - A transport timeout can leave it unknown whether a `PATCH` was applied (remaldi reports `unknown_outcome` and never replays). Re-read the conversation's state rather than resending, and record such conversations as unknown in the manifest. Source: #7, 2026-10-15.
  - Per-conversation status needs an unknown state for requests whose outcome the transport could not report (see `archive-apply`). Source: #7, 2026-10-15.

- [CLI] `undo-command` — **Make `chatctl undo MANIFEST` unarchive exactly the conversations a manifest records as archived.** Undo is the other half of the safety principle.
  - Source: triage, 2026-10-15
  - Depends on: `archive-apply`

### P3 Low

### Unprioritized

## Ready for separate work

### P0 Critical

### P1 High

- [CLI] `select-conversations` — **Add a pure selection function that takes listing items and a cutoff and returns the conversations to archive and the ones skipped, each with a reason.** It is the core of the safety rules and depends on no transport: only fields already recorded in `docs/api-findings.md`.
  - Source: triage, 2026-10-15
  - Starting point: `chatctl/selection.py`. Select only items whose `gizmo_id` is present and null, `is_archived` is false, and `update_time` (ISO 8601) is strictly before the cutoff; skip anything whose fields are missing or unparseable; apply `--exclude` patterns to titles. Tests use placeholder titles and IDs.

### P2 Normal

- [CLI] `archive-manifest-format` — **Design and implement the archive manifest: what it records, where it is written, and how a partly applied run is resumed or undone.** It is the interface between `archive` and `undo` and must land before either depends on it (ARCHITECTURE.md).
  - Source: triage, 2026-10-15
  - Starting point: a short design spec in `docs/specs/` agreed with the user first (location outside the repository, atomic writes, per-conversation status so an interrupted run can be resumed or undone), then a pure module with read, write and validation and its tests.

- [TOOLING] `choose-type-checker` — **Add a static type-check gate for `chatctl/` and `tests/`.** The code is fully annotated (including PEP 695 generics) but nothing checks the annotations, and `scripts/check.sh` has no typecheck step.
  - Source: docket adoption, branch vhata/docket-setup, 2026-10-14
  - Starting point: try mypy `--strict` and basedpyright against the current code, compare noise, then add `scripts/typecheck.sh` and the gate in `scripts/check.sh`, `.githooks/pre-push` (through check.sh) and `docs/QUALITY.md`.

### P3 Low

### Unprioritized
