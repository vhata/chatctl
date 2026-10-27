# Architecture

What the structure is now, the boundaries parallel work must respect, and the invariants reviews check. The original brief is [docs/initial-plan.md](docs/initial-plan.md), designs ahead of the work are in [docs/specs/](docs/specs/) and plans in `plans/`; this file describes the code as it is.

## Layout

- `chatctl/cli.py`: the argparse command-line surface (`stats`, `archive`, `undo`). `stats --target TAB` fetches complete default and archived listings sequentially and prints aggregate summaries only after both succeed. Archive and undo still exit 1 with "not implemented yet".
- `chatctl/stats.py`: pure summaries by kind, reported archive state and elapsed age since `update_time`, with an explicit aware `now`. Duplicate IDs count once per listing; conflicting categories become unknown and unidentified rows remain countable. Output separates the listings and reports overlap without claiming an authoritative account total.
- `chatctl/selection.py`: pure helpers that turn `--older-than` / `--before` into an archive cutoff, and `select_conversations`, which splits conversation listing items into the conversations to archive and the skipped ones, each with a reason. It is the one place the selection safety rules are applied; its docstring gives the order of the checks. Nothing calls it yet.
- `chatctl/client.py`: `ConversationClient.list_conversations()` returns the complete configured listing as a tuple of raw items, with missing fields and duplicate IDs preserved for selection. Its `ListingTransport` protocol returns raw JSON per page. It requests pages of 100 sequentially, uses each page's moving `total`, paces pages, and bounds retries and the page count. Failure raises `ClientError` rather than returning partial history.
- `chatctl/transport.py`: `RemaldiTransport(target)` evaluates a GET-only page script through an explicit remaldi tab target and checks the page's origin before any request. The default is the normal listing; `archived=True` adds `is_archived=true`. Each evaluation fetches its own session; tokens remain inside the page. Listing responses cross into Python as raw JSON text so duplicate keys can be rejected at every depth. Errors contain fixed diagnostic codes, never response bodies or subprocess messages.
- `chatctl/__main__.py`: `python -m chatctl` entry point; the `chatctl` console script is declared in `pyproject.toml`.
- `tests/`: pytest suites for the CLI, stats, selection, the production client and transport, and the transport proof of concept. Production tests fake the listing transport, subprocess and browser fetch; no test uses a logged-in account.
- `discovery/probe.js`: a read-only probe the user pastes into the DevTools console of a logged-in chatgpt.com tab. Outside a browser it exports its pure functions instead of running, which is how `discovery/probe.test.js` tests it with `node --test`.
- `discovery/transport_poc.py`: a read-only proof of concept the user runs to page the conversation listing through `remaldi evaluate` in a logged-in chatgpt.com tab, one page per evaluation, with Python driving the loop. Standard library only; not part of the `chatctl` package. `tests/test_transport_poc.py` tests it behind a fake runner and runs its page script under Node with a fake `fetch`.
- `docs/api-findings.md`: the recorded, dated behaviour of the undocumented ChatGPT endpoints, with evidence.

## Shared interfaces

- The CLI surface in `chatctl/cli.py` (command names, options, exit codes). The README and tests describe it; change all three together.
- `docs/api-findings.md` is the contract between discovery and client code: the client may only rely on behaviour recorded there (rule in [AGENTS.md](AGENTS.md#rules)).
- The archive manifest, once it exists, is the interface between `archive` and `undo`. Its format lands before either command depends on it.

## Invariants

- `chatctl/selection.py` reads no clock and does no I/O: the current time is passed in as a timezone-aware `now` and the cutoff as a timezone-aware datetime. Callers in `cli.py` supply `datetime.now(UTC)`.
- `select_conversations` selects an item only when every check passes, and treats a missing or malformed field as a reason to skip, never as a default. The one deliberate exception is a missing `conversation_template_id` ([docs/DECISIONS.md](docs/DECISIONS.md)). A selected conversation's id contains only ASCII letters, digits, `-` and `_`, so it is safe in a request path. It does not modify its input.
- Every network request in `discovery/probe.js` goes through `makeGet`, which issues GET requests only.
- Every network request the page script in `discovery/transport_poc.py` makes goes through its `get` helper, which issues GET requests only. The script returns shape data and aggregate counts, never the access token or item content.
- Every request the production page script makes goes through its GET-only helper. The session is never returned to Python. The client strictly decodes both the remaldi envelope and listing JSON, rejecting duplicate keys before selection can observe them. It exposes no per-conversation paths or mutations; any future ID-based request must percent-encode the ID with `quote(id, safe="")`.
- The safety rules in [AGENTS.md](AGENTS.md#rules) (dry run without `--apply`, a fixed manifest before the first change, never touching project or custom GPT conversations, no account data in the repository) apply to all code; this file does not restate them.

## Isolation for concurrent work

Each worktree owns its mutable state: its own `.venv/` created by `bash scripts/setup.sh`, and `.pytest_cache/`, `.ruff_cache/` and `.mypy_cache/`, all ignored by git. Nothing binds ports or writes outside the worktree. Hooks come from each worktree's own `.githooks/` because `core.hooksPath` is relative.

## Where to look first

- [AGENTS.md](AGENTS.md) for the rules, then [docs/api-findings.md](docs/api-findings.md) before touching anything that talks to ChatGPT.
- `chatctl/cli.py` for the command surface.
