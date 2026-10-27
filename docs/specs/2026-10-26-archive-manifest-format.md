# Archive manifest format

Status: proposed; implementation awaits the user's agreement.

## Problem and scope

An archive run must fix its complete selection before changing ChatGPT,
retain a useful record after interruption, and let undo distinguish changes
made by the run from conversations it never changed. A JSON file cannot
commit atomically with a remote request: some outcomes will remain unknown.
The design preserves that uncertainty rather than claiming exactly-once
execution or replaying a request whose result was lost.

This proposes version 1 of the manifest and its storage/transition API for
`archive-manifest-format` in [TODO.md](../../TODO.md). It does not implement
the module, transport, archive, resume, or undo commands. The existing
[CLI](../../chatctl/cli.py) remains unimplemented. The
[safety rules](../../AGENTS.md#rules) and
[selection predicate](../../chatctl/selection.py) remain authoritative.

## Evidence and acceptance blockers

[API findings](../api-findings.md), questions 7 and 8, record the UI's
archive/unarchive PATCH and HTTP 200 `{"success": true}` response.
[The transport decision](../DECISIONS.md) records that a timed-out remaldi
evaluation may still execute and is never replayed by remaldi.

The queue's newer `patch-listing-disagreement` evidence contradicts the
older question 13 finding: an acknowledged archive can appear archived in
one listing and active in another. Neither a successful response alone nor
an archived-listing hit proves a consistent, attributable state change.
Absence from a listing never proves active, deleted, or successfully undone.

Before archive/resume/undo integration may mutate an account, the user must
gather and record evidence resolving:

- `test-minimal-archive-patch`: the supported request and response contract
  for both archive and unarchive, including definite rejection semantics.
- `patch-listing-disagreement`: which read is authoritative, how to detect
  stale/conflicting results, and when verification is conclusive.
- Stable account/workspace identity: session `user` and `account` objects
  are recorded, but their identity fields and workspace-switch behaviour
  are not. Do not invent an identity field or infer identity from a tab ID.
- How to establish that a timed-out evaluation can no longer issue its
  mutation. An elapsed timeout or a read of the old state is insufficient.

These block live integration, not offline implementation of a manifest
module after design agreement. Agents prepare fixtures and code; only the
user runs real-account experiments. No endpoint beyond recorded findings
is assumed by this spec.

## Private storage

Proposed default: `~/.local/state/chatctl/manifests/`, independent of the
working directory, with no configurable output path in version 1. Files
are named `archive-run-<UTC timestamp>-<random UUID>.json`; names contain no
conversation title, conversation ID, or account identifier. Print the
absolute path before the first mutation and in every completion/error
summary that has a manifest.

Create the chatctl state directory and its descendants with mode `0700`,
and manifests, temporary files, and the persistent lock file with `0600`
at creation, regardless of umask. Check current-user ownership and reject
group/other access on existing managed directories and files. Do not
silently chmod an existing insecure store and proceed.

Resolve and validate the path before use: reject symlinks in managed path
components, non-regular files, manifest hard links, and a store inside a
Git checkout (including worktrees identified by a `.git` file). Use
directory-relative, no-follow file operations and descriptor checks to
avoid validating one path and then opening a substituted one. Ordinary
ancestors such as the home directory need not have mode `0700`, but may
not be writable by other users. Unsupported filesystem/locking/durability
semantics fail before mutation; version 1 targets a local POSIX filesystem.

Store the selected IDs, necessary selection metadata, and bounded outcome
codes only. Omit titles, conversation contents, tokens, cookies, session
objects, browser targets, request headers, response bodies, and arbitrary
exception text. Criteria can include private text in exclusion patterns;
the entire file is private even without titles. Account binding is a
SHA-256 digest of a versioned, unambiguous encoding of the proven stable
user and account/workspace identity; it is a comparison value, not a
credential or anonymization guarantee.

Do not commit runtime manifests or put them in `.context/`. Existing ignore
patterns are a fallback, not the storage boundary. Keep manifests until the
user removes them; no automatic expiry, upload, or separate failures file.
Filesystem permissions do not provide encryption at rest or protect
against other processes running as the same user.

## Version 1 document

A UTF-8 JSON object, emitted with a trailing newline. Example values below
are synthetic; `account_binding` stands for a real 64-character hex digest.

```json
{
  "schema_version": 1,
  "run_id": "00000000-0000-4000-8000-000000000001",
  "operation": "archive",
  "created_at": "2026-10-26T12:00:00Z",
  "updated_at": "2026-10-26T12:00:00Z",
  "revision": 0,
  "account_binding": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "selection": {
    "evaluated_at": "2026-10-26T12:00:00Z",
    "cutoff": "2026-07-28T12:00:00Z",
    "criteria": {"older_than": "90d", "before": null, "exclude": []}
  },
  "undo_started_at": null,
  "conversations": [
    {
      "id": "example-conversation",
      "original": {
        "update_time": "2026-01-01T00:00:00Z",
        "is_archived": false,
        "gizmo_id": null,
        "conversation_template_id_present": false,
        "conversation_template_id": null
      },
      "archive": {"status": "pending", "reason": null, "attempts": []},
      "undo": {"status": "not_eligible", "reason": null, "attempts": []}
    }
  ]
}
```

`schema_version`, run ID, operation, creation time, account binding,
selection, and the ordered IDs and `original` snapshots are immutable.
Selection time fixes the relative cutoff once; resume never recalculates
it. `criteria` has exactly one non-null cutoff input and ordered exclusion
patterns with the CLI's case-insensitive semantics. Store validated inputs
and normalized UTC timestamps. The selected snapshot records explicit null
membership and false archive state; it does not substitute for a fresh
preflight check. A missing template field remains distinguishable from a
present null field. Creation time and titles are unnecessary for recovery.

`revision` increases by one per committed replacement. `updated_at` records
that write; revision, not wall-clock ordering, detects stale writers.
`undo_started_at` is set once, durably, before the first undo intent. After
that point this manifest cannot resume archiving. Archive and undo records
are separate so undo never erases archive evidence. Summary counts and
overall completion are derived, not independently stored.

Both direction records have `status`, nullable enumerated `reason`, and an
ordered `attempts` array. Each attempt contains a unique `attempt_id`,
`started_at`, nullable `finished_at`, `outcome` (`in_flight`, `succeeded`,
`failed`, or `unknown`), nullable bounded `error_code` and `http_status`,
`acknowledged` (boolean), and nullable `verification`. Verification contains
`checked_at` and `state` (`active`, `archived`, `conflicting`, `unavailable`)
from the evidence-backed read contract. It never contains raw API data.

An intent starts with `in_flight`, no finish time, no acknowledgement, and
no verification. A received positive acknowledgement is itself checkpointed
before verification. A verified target state plus a positive acknowledgement
can establish `succeeded` only under the accepted API contract. A target
state observed without an acknowledgement cannot establish attribution.
An unknown attempt can gain acknowledgement only from a late result tied
to that exact attempt, never from a listing observation.

Direction status agrees with the newest attempt, except `pending` and
`skipped` have no attempts, and undo initially has `not_eligible`. A failed
direction may append another attempt only under the retry rules below.
Terminal attempt evidence is preserved; reconciliation of unknown attempts
adds verification/late-result evidence without deleting the prior error.
Reasons use a documented allowlist, for example `membership_changed`,
`selection_changed`, `already_active`, `already_archived`, `state_conflict`,
`definite_rejection`, `transport_unknown`, and `interrupted`. Unknown codes
are rejected; implementation defines the exhaustive enum and its tests.

## Validation and module boundary

The standard-library-only module supplies pure document validation,
creation from a complete validated selection, and transition functions.
A small storage layer owns private-path checks, locking, load, initial
publication, and replacement. Neither layer selects live conversations,
reads credentials, invokes remaldi, or sends network requests. The caller
provides timestamps, run/attempt IDs, account binding, and typed outcomes.

Reject the whole file before dispatch on malformed JSON, duplicate keys at
any depth, unknown version/fields/enums, bools masquerading as integers,
non-finite numbers, invalid timestamps/UUIDs/digests, duplicate IDs, IDs
outside the selection module's ASCII alphabet, or inconsistent states.
Validate membership snapshots, cutoff/criteria consistency, nonnegative
revision, attempt identity uniqueness, status/attempt agreement, and undo
eligibility. A non-null template value or non-false original archive state
is invalid. Empty selections are valid no-op manifests. Do not repair a
file by dropping invalid entries or treating missing statuses as success.

Transitions preserve immutable fields and prior attempts and require the
expected revision. Loading arbitrary old versions does not migrate them;
migration requires a separate reviewed design. A private manifest is not
cryptographic proof against deliberate same-user editing; account and
live-state checks remain necessary even for schema-valid input.

## Atomic publication and concurrency

Hold one advisory exclusive lock in the private chatctl state directory
from validation through the end of any archive, resume, or undo apply.
It serializes all managed runs, including overlapping manifests, rather
than merely protecting one file. Fail clearly if busy. Use a persistent
lock inode whose OS lock is released on process exit; never delete it or
use a stale PID file as authority. Dry runs never acquire mutation intent.

For initial creation and every checkpoint:

1. Validate the entire proposed next document and expected revision while
   locked. For creation, the complete ordered selection must be present.
2. Create a unique `0600` temporary file in the destination directory,
   serialize the full document, flush it, and `fsync` its file descriptor.
3. Initially publish with an atomic no-clobber operation; a collision must
   leave the existing file untouched. For updates, atomically replace the
   existing manifest after checking its identity and expected revision.
4. `fsync` the containing directory before reporting a durable commit.
   Sync newly created directory entries in their parents as well.

Never truncate the published file in place. Readers see the old complete
revision or the new complete revision. A replace is not considered durable
until directory sync succeeds. If any write, flush, replacement, sync, or
permission check fails, stop all dispatch immediately and exit non-zero.
Do not proceed on the strength of a temporary file or an in-memory result.
Leave the last valid manifest usable; report that a post-replace sync error
may leave either revision after a crash. A prior durable intent then
protects any request whose result could not be saved. Orphan temporaries
are private, never loaded as manifests, and may be removed under the lock.

## Dispatch, interruption, and partial failure

The caller compares the current proven account binding with the manifest
before any mutation and rechecks the explicit browser target, origin, and
identity for every dispatch. A mismatch or unavailable identity stops the
run. Under the global lock, inspect managed manifests for unresolved
`in_flight`/`unknown` attempts before starting any new mutation run: a
crashed process's browser evaluation may outlive its OS lock.

For each candidate in manifest order:

1. Read fresh state using the accepted verification contract. Recheck
   ordinary membership and, for archive, the saved cutoff/exclusions.
   Missing, conflicting, moved, already-archived, or newly excluded items
   are skipped with a bounded reason; never expand or replace the selection.
2. Durably checkpoint an `in_flight` attempt before sending exactly one
   request. No request may be sent if that checkpoint fails.
3. Record the acknowledgement and verification, then durably checkpoint
   the outcome before advancing. State observed in the opposite direction
   after an acknowledgement is a conflict, not permission to replay.

| Outcome | Stored result and next step |
| --- | --- |
| Positive acknowledgement and conclusive target-state verification | `succeeded`; continue after checkpoint. |
| Proven request not dispatched, or evidence-backed rejection guaranteeing no change | `failed`; checkpoint, then continue for an item-specific failure. |
| Timeout, disconnected browser, ambiguous response/5xx, malformed success, or inconclusive verification | `unknown`; checkpoint and stop mutations for the run. |
| Authentication/account failure, systemic read failure, or persistence failure | Stop the run; preserve pending items and any durable intent. |

Do not label every non-2xx response a definite failure. GETs may use bounded
retries/backoff; PATCH retries require proof of non-dispatch/non-application
and an evidence-backed retry policy. Default version 1 behaviour makes no
automatic PATCH retry. A new explicit apply may retry `failed` entries
after preflight; it never automatically retries unknown ones.

On interruption, finish a safe checkpoint if possible, print counts and
the path, and exit non-zero. On load, any durable `in_flight` means unknown
for recovery, even if the crash happened just before dispatch. Recovery
must not assume that killing remaldi cancelled browser execution. A crash
after receiving success but before saving it has the same uncertainty.
Counts distinguish pending, skipped, succeeded, failed, unknown, and undo
progress. Exit zero only when there are no failed, unknown, or unfinished
eligible items; explain safety skips separately from successful changes.

## Reconciliation, resume, and undo

Reconciliation uses read-only requests and preserves acknowledgement,
errors, and the distinction between observed state and this run's effect.
An unknown request observed at its target state stays unknown unless its
attributable positive result and the accepted verification contract settle
it. Observing the old state also leaves it unknown while delayed execution
is possible. Never resend to discover whether a request already ran.
If the evidence cannot settle it, leave it held and direct the user to
inspect/manage that conversation in ChatGPT; editing JSON is not recovery.
Global dispatch remains blocked until unresolved attempts are conclusively
settled and no late mutation can run. Version 1 supplies no force override.

Proposed future CLI: `chatctl archive --resume MANIFEST [--apply]`, mutually
exclusive with selection flags. It uses the original file and order, skips
successful/skipped entries, and processes only pending or safely failed
entries after preflight. A dry run validates and previews without creating
files, updating observations, changing permissions, or sending PATCHes.
Only explicit `--apply` persists recovery transitions or dispatches. This
CLI extension belongs to `archive-apply`, not the manifest module task.

`chatctl undo MANIFEST` retains its existing dry-run default. With
`--apply`, it uses the same private original manifest, account binding,
global lock, write-ahead intents, outcome rules, and atomic checkpoints.
Version 1 refuses apply from a copied file outside the managed store; it
does not import or silently fork a manifest's recovery history.

- Eligible IDs are exactly those with archive `succeeded`, never pending,
  skipped, failed, or unknown archive outcomes. Undo never selects from
  the current archived listing. The first undo intent seals the archive
  phase; it does not archive still-pending entries first.
- Recheck current membership and state. Skip unsafe/unclear membership;
  if conclusively already active, record `skipped`/`already_active` without
  sending a PATCH or claiming this undo changed it. An archived state
  permits undo only with the original attributable archive success.
- Preserve archive results and append undo attempts. Partial undo is
  resumable by repeating `undo MANIFEST --apply`: never replay successful
  undo entries or an unknown undo attempt. Unknown undo outcomes impose
  the same global hold and reconciliation rules as unknown archives.
- The manifest cannot detect every intervening manual unarchive/rearchive.
  Undo is an explicit request to restore confirmed run members to active,
  not a promise to restore all intervening user intent or deleted content.
  It cannot guarantee a state snapshot against concurrent web UI changes.

## Acceptance checks for later implementation

Use synthetic IDs and fake filesystem/transport outcomes only. The module
work must test strict validation and immutable-field transitions, both
directions' histories, and rejection of unsupported/corrupt manifests.
Storage tests must cover permissive umask, existing insecure paths,
symlinks/hard links, Git/worktree paths, filename collisions, concurrent
writers and stale revisions, and injected failures at each publication
step. Readers must never consume a torn document.

Integration tests in the later archive/undo tasks must inject crashes
before intent, after durable intent/before send, after send/before result,
after acknowledgement/before checkpoint, and during undo. Assert no PATCH
before durable selection/intent, no dispatch after persistence failure,
no unknown replay, no cross-account application, a fixed mutation set,
preserved archive evidence, and cross-manifest serialization/unknown holds.
Include contradictory listings, changed membership, already-active undo,
partial item failures, bounded read retries, and a fully read-only dry run.

## Agreement requested

Agree or revise the private fixed storage location, strict versioned JSON
with separate archive/undo histories, conservative global hold for unknown
outcomes, and manifest-based resume/undo semantics. After agreement,
implement only the pure manifest and private storage module with tests as
`archive-manifest-format`; archive/resume and undo integration remain their
existing dependent tasks, subject to the API evidence blockers above.
