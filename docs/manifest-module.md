# Offline manifest module

The manifest is recovery infrastructure for future archive and undo
commands. It is not wired into the CLI: archive previews stay read-only,
and `archive --apply` and `undo` still fail before browser access.
The [approved design](specs/2026-10-26-archive-manifest-format.md) defines
the schema and safety rules. This document describes the Python interface.

## Pure document operations

`chatctl.manifest` uses JSON dictionaries and standard-library types.
All public transitions validate their input, return a deep copy, and
increment the revision exactly once. They do not read a clock, create
files, invoke remaldi or issue requests. Invalid input raises
`ManifestError` with bounded diagnostics that omit private input values.

- `create(selected=..., run_id=..., now=..., binding=..., evaluated_at=...,
  cutoff=..., older_than=... | before=..., exclude=...)` freezes a complete
  sequence of selected listing rows. Every supplied row must pass the
  existing selector; duplicates and unsafe rows reject the whole input.
  Titles are used for exclusion validation and then discarded. Missing
  versus null template metadata remains distinguishable.
- `account_binding(user_identity, workspace_identity)` hashes a versioned
  JSON array containing two caller-proven stable identities. It establishes
  no API identity contract; selecting the actual identity fields still
  needs user-gathered evidence.
- `validate`, `loads` and `dumps` enforce the version-1 schema. Unknown
  fields, duplicate JSON keys, invalid numbers, unsafe membership and
  inconsistent histories fail closed. Serialization ends with a newline.
- `begin_attempt` requires pending or definitely failed status. It appends
  an unresolved intent with a caller-supplied unique attempt UUID.
- `acknowledge` checkpoints a positive result tied to that attempt UUID.
  Verification cannot establish success in the same checkpoint as the
  first acknowledgement.
- `record_outcome` records verified success, definite failure, or unknown.
  An HTTP code alone is never converted into an outcome. The caller must
  supply evidence-backed verification and quiescence classifications.
- `interrupted` converts a durable in-flight intent to unknown. Reading a
  file does not rewrite it; `holds` already treats in-flight as unknown.
- `skip` preserves prior failed attempts and refuses to overwrite an
  unresolved or successful attempt.
- `start_undo` seals the archive phase. Persist this revision before
  creating an undo intent. New archive attempts are then prohibited;
  existing unknown archive attempts can still receive recovery evidence.
- `validate_transition` independently checks old and new documents at the
  storage boundary, so callers cannot bypass immutability or checkpoint
  ordering by constructing a dictionary themselves.
- `holds` returns a global execution hold plus account/conversation pairs
  held by unresolved attempts. Proven quiescence releases the global hold;
  an unknown outcome continues to hold its own account/conversation pair.

Transitions take `expected_revision` and `now`. Attempt operations also
identify the conversation, direction (`archive` or `undo`) and attempt.
A late acknowledgement must name the exact unresolved attempt. Reconciled
success preserves earlier error codes and quiescence evidence.

The exhaustive allowlists are `REASONS`, `SKIP_REASONS` and `ERROR_CODES`
in [manifest.py](../chatctl/manifest.py). They contain fixed classifications
such as `membership_changed`, `transport_unknown`, `not_dispatched` and
`definite_rejection`; callers cannot store raw exceptions or response text.

## Private persistence

`ManifestStore` uses `~/.local/state/chatctl/manifests/`. It accepts a
`home` dependency for isolated tests; the CLI exposes no destination
option. Use it as a context manager. Opening with `create=False` reads an
existing store without creating directories, touching permissions or
acquiring the mutation lock. `create=True` can initialize private storage.

A `locked()` context takes the persistent `chatctl/mutation.lock` inode
with a nonblocking exclusive advisory lock. Keep this context alive across
an entire future apply/resume/undo operation, including preflight,
checkpoints and dispatch; a per-write lock is insufficient.

`publish(document)` writes a fresh revision-zero selection with atomic
no-clobber publication and returns its absolute path. `checkpoint(name,
document, expected_revision=...)` compares against the current on-disk
revision and validates the complete transition before replacing the file.
Both sync the temporary file and containing directory. New directories
and their parent entries are synced too. `load(name)` accepts only a
managed basename whose timestamp and run ID match its document.

`scan()` validates every published file. Under the lock,
`dispatch_allowed(binding, conversation_id)` checks cross-manifest holds.
Call it **before** writing a new intent: that intent itself imposes a hold.
A positive result does not replace current account comparison, membership
preflight, or the requirement to persist the intent before dispatch.

The store checks current-user ownership and private modes of managed
paths and files, refuses symlinks, hard links and nonregular files, checks
ancestor writability, and rejects Git checkouts. Directory descriptors and
inode checks keep operations tied to the validated paths. Orphan `.tmp-`
files are never read as manifests. There is no automatic cleanup or expiry.

Any persistence failure stops use of that store instance. A failure after
publication but before directory sync reports uncertain durability: either
complete revision might survive a crash. A new process must reopen,
validate and reconcile the stored evidence before attempting further work.
The implementation targets local POSIX filesystems; unsupported locking or
sync semantics fail closed. A restrictive umask that prevents opening a
new directory can also fail safely before any manifest is published.

These safeguards do not defend against malicious processes running as the
same user, provide encryption, or establish live API behavior. Real-account
identity, preflight/readback and delayed-execution evidence remain required
before the future mutation integration can use this module.
