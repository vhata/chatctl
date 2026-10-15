# chatctl

A local command-line tool for selectively archiving old ChatGPT
conversations. For example: archive everything that hasn't been touched in
90 days, but leave recent chats and project conversations alone.

ChatGPT's own UI can archive one conversation at a time, or all of them at
once. chatctl is for everything in between.

## Status

Early. So far there is:

- a CLI skeleton (`chatctl stats`, `chatctl archive`, `chatctl undo`) that
  parses and validates its options, then exits with "not implemented yet";
- a read-only [discovery probe](discovery/README.md) for working out how
  the ChatGPT web app's internal API behaves.

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

## Development

```bash
bash scripts/setup.sh   # dependencies and git hooks for this checkout
bash scripts/check.sh   # format check, lint, pytest and the probe's tests
```

See [`AGENTS.md`](AGENTS.md) for the working rules and
[`docs/QUALITY.md`](docs/QUALITY.md) for the gates. Work is tracked in
[`TODO.md`](TODO.md) using [docket](docket/README.md).

## Credits

Built with Claude (Anthropic).
