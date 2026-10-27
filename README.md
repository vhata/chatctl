# chatctl

A local command-line tool for selectively archiving old ChatGPT
conversations. For example: archive everything that hasn't been touched in
90 days, but leave recent chats and project conversations alone.

ChatGPT's own UI can archive one conversation at a time, or all of them at
once. chatctl is for everything in between.

## Status

Early. So far there is:

- `chatctl stats --target TAB`, a read-only summary of the default and
  archived conversation listings by kind, reported archive state and age;
- CLI skeletons for `chatctl archive` and `chatctl undo` that parse and
  validate options, then exit with "not implemented yet";
- a read-only [discovery probe](discovery/README.md) for working out how
  the ChatGPT web app's internal API behaves;
- a read-only proof of concept that pages the conversation listing from
  a local process through a logged-in browser tab
  ([transport proof of concept](discovery/README.md#transport-proof-of-concept));
- a read-only conversation client using that remaldi transport, with
  sequential pagination, bounded retries and strict JSON decoding, tested
  against fake transports and used by `stats`.

Nothing in this repository can archive anything yet. Findings about the
API go in [`docs/api-findings.md`](docs/api-findings.md). The original brief
is [`docs/initial-plan.md`](docs/initial-plan.md).

## Safety principle

> Make it difficult to accidentally archive something and trivial to
> determine exactly what the tool changed.

The design rules that follow from it:

- Every command that changes anything is a dry run unless `--apply` is
  given.
- The full set of conversations to change is fixed and written to a local
  manifest before the first change.
- Undo works from that manifest, and only touches what it lists.
- Conversations that belong to ChatGPT Projects, and conversations with
  custom GPTs, are never archived. When membership is unclear, the
  conversation is skipped.
- Everything runs locally. Conversation metadata is not sent anywhere
  except ChatGPT itself.

## Setup

Requires [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 if
needed.

```bash
uv sync
uv run chatctl --help
```

## Conversation statistics

With remaldi installed and a logged-in chatgpt.com tab open in Vivaldi
with remote debugging enabled, pass that tab's explicit remaldi target:

```bash
uv run chatctl stats --target 'TAB_ID'
```

See the [browser transport setup](discovery/README.md#transport-proof-of-concept)
for the browser and remaldi prerequisites. The command makes GET requests
only, paging the default listing and then the archived listing one at a
time. It prints aggregate counts without conversation titles or IDs. A
failed or interrupted listing produces a nonzero exit and no partial
summary.

Each listing has its own counts. The listings can disagree about archive
state, so the output reports their overlapping ID count rather than a
combined account total or an authoritative archive state. Within a
listing, repeated nonempty string IDs count once. Conflicting categories
for the same ID count as unknown in that dimension. Rows without a usable
ID count individually and are reported separately.

Kinds follow the observed `gizmo_id` scheme: null means ordinary, `g-p-`
means project, and other `g-` prefixes mean custom GPT. Missing, malformed
or unfamiliar values count as unknown, as does a null `gizmo_id` with a
non-null `conversation_template_id`. These are descriptive counts, not
archive eligibility decisions. Archive state requires an exact boolean.

Age means elapsed time since `update_time`, using one UTC clock value for
both listings: under 30 days, 30 to under 90 days, 90 to under 365 days,
and 365 days or more. Future timestamps and missing, invalid or timezone
unspecified timestamps have separate categories. Creation time is unused.

## Development

```bash
bash scripts/setup.sh   # dependencies and git hooks for this checkout
bash scripts/check.sh   # format check, lint, type check, pytest and the probe's tests
```

See [`AGENTS.md`](AGENTS.md) for the working rules and
[`docs/QUALITY.md`](docs/QUALITY.md) for the gates. Work is tracked in
[`TODO.md`](TODO.md) using [docket](docket/README.md).

## Credits

Built with Claude (Anthropic).
