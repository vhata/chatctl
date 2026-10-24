# Deferred work

Ordinary follow-ups and bugs found during other work live here. Whole-codebase review findings promoted for separate work live in [review/BACKLOG.md](review/BACKLOG.md). Follow [docket/TODO_GUIDE.md](docket/TODO_GUIDE.md) before adding, claiming, moving or resolving an entry. Entries in **Ready for separate work** are unblocked and available now; an understood entry with an unresolved `Depends on:` or a `Blocked by:` goes in **Waiting** until it clears.

## Needs triage

### P0 Critical

### P1 High

- [API] `patch-listing-disagreement` — **Find out why a conversation archived by a direct `PATCH` from the page appears in both listings, archived in one and not in the other, and stays in the sidebar.** chatctl's selection, verification and undo read the listings, so they cannot rely on either one until it is known which reflects the server's state and whether the other catches up.
  - Source: user's minimal-PATCH test for `capture-archive-patch-headers`, 2026-10-24
  - Related: `archive-apply`, `undo-command`
  - Evidence, one throwaway conversation, 2026-10-24: a `PATCH /backend-api/conversation/<id>` with `{"is_archived": true}`, made from the tab's (wrapped, non-native) `fetch` with only `Authorization` and `Content-Type` set by the caller, returned 200 `{"success": true}`. Afterwards the conversation was in `?is_archived=true` with `is_archived: true` and in Settings, Archived chats, but also in the default listing with `is_archived: false` and a different `update_time`, and in the sidebar after a fresh load in a new tab. When archived from the web UI on 2026-10-14 it left the default listing (`docs/api-findings.md`, question 13).
  - Starting point: repeat the read-only two-listing check later to see whether the default listing catches up; compare against a second throwaway archived from the UI with the Network tab recording every request it makes; record the request headers the wrapped `fetch` actually sent.

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

- [API] `test-minimal-archive-patch` — **Find out whether an archive `PATCH` made from the page with only `Authorization` and `Content-Type` is accepted, and if not, which of the web app's own headers it needs.** The UI sends device and account headers whose values chatctl would have to reproduce (`docs/api-findings.md`, question 11), and no code may send a `PATCH` until this is known.
  - Source: todo/choose-browser-transport (#7), 2026-10-24
  - Remaining from: `capture-archive-patch-headers`
  - Blocked by: the user archiving and then unarchiving a throwaway conversation from the tab, once with only those two headers and, if that fails, adding the app's headers back until it succeeds.
  - Starting point: a one-off snippet for the console or `remaldi evaluate` that sends `PATCH /backend-api/conversation/<id>` with `{"is_archived": true}` for an ID the user pastes in, then the same with `false`; record the outcome under question 11.

### P2 Normal

- [CLI] `stats-command` — **Make `chatctl stats` summarise the listing: counts by kind (ordinary, project, custom GPT), archived state and age.** A read-only command is the first end-to-end use of the client and the safest one.
  - Source: triage, 2026-10-15
  - Depends on: `conversation-client`

- [CLI] `archive-dry-run` — **Make `chatctl archive` without `--apply` list the selection and its summary against the live listing.** This is the brief's first workflow, and it changes nothing.
  - Source: triage, 2026-10-15
  - Depends on: `conversation-client`
  - The `--exclude` help should say that a conversation with a null title never matches a pattern. Source: review of #6, 2026-10-15.

- [CLI] `archive-apply` — **Make `chatctl archive --apply` write the manifest, then archive exactly the conversations in it, recording each result.** This is the mutation the tool exists for.
  - Source: triage, 2026-10-15
  - Depends on: `archive-dry-run`, `archive-manifest-format`, `test-minimal-archive-patch`
  - A transport timeout can leave it unknown whether a `PATCH` was applied (remaldi reports `unknown_outcome` and never replays). Re-read the conversation's state rather than resending, and record such conversations as unknown in the manifest. Source: #7, 2026-10-15.

- [CLI] `undo-command` — **Make `chatctl undo MANIFEST` unarchive exactly the conversations a manifest records as archived.** Undo is the other half of the safety principle.
  - Source: triage, 2026-10-15
  - Depends on: `archive-apply`

### P3 Low

### Unprioritized

## Ready for separate work

### P0 Critical

### P1 High

- [API] `conversation-client` — **Page the full conversation listing through the transport recorded in `docs/DECISIONS.md` (`remaldi evaluate` in a logged-in tab).** Every command needs the listing, and its pagination has a misleading `total` (`docs/api-findings.md`, question 2).
  - Source: triage of `docs/api-findings.md`, 2026-10-15
  - Starting point: `discovery/transport_poc.py` already does this read-only for aggregate counts; the client returns the listing fields selection needs instead. Offset/limit paging with `limit=100`, stopping at `offset + len(items) >= total` or an empty page; requests one at a time with bounded retries and backoff on 429 and 5xx (AGENTS.md rules). Test against fixtures shaped like the recorded responses, behind a fake transport.
  - Decode responses rejecting duplicate JSON keys (`object_pairs_hook`): `json.loads` keeps the last duplicate, so a doubled `gizmo_id` could read as null. Source: review of #6, 2026-10-15.
  - Percent-encode ids in request paths (`quote(id, safe="")`) even though selection restricts their characters. Source: review of #6, 2026-10-15.
  - With remaldi, always pass an explicit `--target` and check `location.origin` in the page: remaldi's default target is Vivaldi's privileged UI page. Decide whether fetching the session on every page (two GETs per page in the proof of concept) is acceptable or how to reuse the token without it leaving the page. Source: #7, 2026-10-15.

### P2 Normal

- [CLI] `archive-manifest-format` — **Design and implement the archive manifest: what it records, where it is written, and how a partly applied run is resumed or undone.** It is the interface between `archive` and `undo` and must land before either depends on it (ARCHITECTURE.md).
  - Source: triage, 2026-10-15
  - Starting point: a short design spec in `docs/specs/` agreed with the user first (location outside the repository, atomic writes, per-conversation status so an interrupted run can be resumed or undone), then a pure module with read, write and validation and its tests.
  - Per-conversation status needs an unknown state for requests whose outcome the transport could not report (see `archive-apply`). Source: #7, 2026-10-15.

### P3 Low

### Unprioritized
