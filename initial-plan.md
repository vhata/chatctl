# ChatGPT Selective Bulk Archiver

## Goal

Build a small local tool for selectively archiving large numbers of old ChatGPT conversations.

ChatGPT currently supports:

- archiving individual conversations manually;
- archiving all conversations at once.

What is missing is a way to do things like:

> Archive every ordinary conversation that has not been touched in 90 days, while leaving recent chats and project conversations alone.

The tool should make this operation safe, inspectable, reversible, and easy to run locally.

This is primarily a personal utility, not something that needs to be productionized or distributed.

---

## Desired workflow

The ideal user experience is approximately:

```bash
chatgpt-archive --older-than 90d
```

which produces a dry run:

```text
Found 1,284 active conversations.

917 conversations have not been updated in the last 90 days.

Oldest:
2023-04-19  Some old conversation

Newest selected:
2026-07-08  Another conversation

DRY RUN — no conversations were modified.
```

The user can inspect the selection before doing anything.

Then:

```bash
chatgpt-archive --older-than 90d --apply
```

archives exactly those conversations.

An explicit date should also be supported:

```bash
chatgpt-archive --before 2026-07-01
```

The default must always be **dry run**. Nothing should change unless `--apply` is supplied.

---

# Selection semantics

Use a conversation's **last update time**, not its creation time, when deciding whether it is old.

For example:

- Created: January 2024
- Last updated: October 2026

That conversation is active and should not be considered old.

A chat that has genuinely not been touched since January 2024 is a good archive candidate.

Support at minimum:

```text
--before YYYY-MM-DD
--older-than 90d
```

It would also be useful to support exclusions such as:

```text
--exclude REGEX
```

Potential future options:

```text
--include REGEX
--keep-starred
--after DATE
--limit N
```

Do not overbuild these initially.

---

# Projects

An important requirement is:

> **Do not archive conversations belonging to ChatGPT Projects.**

The current ChatGPT web application appears to represent project conversations separately from the ordinary conversation history, but this is undocumented behavior and must be investigated.

The tool should explicitly determine whether a conversation belongs to a Project rather than merely assuming that fetching one particular endpoint excludes them.

If there is any ambiguity, the safe behavior is:

> skip the conversation.

Never accidentally bulk-archive project conversations.

---

# Safety model

This tool performs a potentially large account mutation, so safety matters more than convenience.

## 1. Dry run by default

This:

```bash
chatgpt-archive --older-than 90d
```

must never modify anything.

Mutation requires:

```bash
--apply
```

---

## 2. Show what is about to happen

Before applying, display useful statistics such as:

```text
Active ordinary conversations: 1,284
Selected for archive:            917
Excluded:                        367
```

Also show a sample of the oldest/newest selected conversations.

Optionally support:

```bash
--list
```

to print every selected conversation.

---

## 3. Write a manifest before changing anything

Before the first mutation, write a JSON manifest containing every conversation about to be modified.

For example:

```json
{
  "created_at": "2026-10-07T17:20:00Z",
  "operation": "archive",
  "criteria": {
    "older_than": "90d"
  },
  "conversations": [
    {
      "id": "...",
      "title": "...",
      "create_time": "...",
      "update_time": "...",
      "is_archived": false
    }
  ]
}
```

The manifest must be written before mutations begin.

Use a filename such as:

```text
archive-run-2026-10-07T172000Z.json
```

---

## 4. Undo

Support:

```bash
chatgpt-archive --undo archive-run-2026-10-07T172000Z.json
```

This should unarchive only the conversations listed in that manifest.

Do not implement undo by blindly changing everything currently archived.

The manifest represents the exact mutation set.

---

## 5. Partial failure handling

If 600 conversations are selected and request 427 fails:

- do not abandon the run;
- record which operations succeeded;
- record which failed;
- continue where reasonable;
- print a clear summary.

For example:

```text
Archived: 596
Failed:     4

Failures written to:
archive-run-2026-10-07T172000Z.failures.json
```

Retries should be conservative.

---

# ChatGPT API investigation

The ChatGPT web application currently appears to use internal endpoints resembling:

```http
GET /backend-api/conversations
```

for conversation history, and:

```http
PATCH /backend-api/conversation/<conversation-id>

{
  "is_archived": true
}
```

for archiving.

These are **undocumented internal APIs**.

Do not assume these exact paths or payloads are still correct.

Before implementing:

1. inspect current ChatGPT web traffic;
2. identify how conversation lists are fetched;
3. identify how archive/unarchive is performed;
4. identify pagination behavior;
5. determine how project conversations are represented;
6. determine whether archived and active conversations are listed separately;
7. verify what timestamp fields are available;
8. determine authentication requirements.

Prefer mimicking the smallest legitimate request that the current ChatGPT web UI itself makes.

Avoid scraping rendered HTML if a structured endpoint is available.

---

# Authentication

Do not ask the user to paste permanent account credentials into the program.

Possible approaches, in approximate order of preference:

## Option A — execute inside an existing authenticated browser session

For an initial prototype, a JavaScript script executed from the ChatGPT browser tab may be easiest.

Advantages:

- already authenticated;
- no credential storage;
- good for discovering APIs;
- easy to prototype.

This may initially be the best way to validate the idea.

---

## Option B — local CLI using a temporary session token

A Python CLI could make the same requests directly using whatever temporary credential the current web app uses.

If this approach is used:

- never hard-code the credential;
- never save it in the repository;
- never log it;
- ideally read it from an environment variable;
- warn that it is effectively an account credential while valid.

For example:

```bash
CHATGPT_TOKEN=... chatgpt-archive --older-than 90d
```

Do not make the user store it in a `.env` file unless necessary.

---

## Option C — browser automation

A local script could use an authenticated Chromium profile via Playwright or similar.

This avoids manually copying tokens but introduces more complexity.

Consider this only if direct requests are inconvenient or authentication changes frequently.

---

# Suggested implementation strategy

Start simple.

## Phase 1 — read-only discovery tool

Build something that:

1. accesses the currently authenticated account;
2. retrieves all active conversations;
3. paginates through the entire history;
4. captures at least:

```text
id
title
create_time
update_time
archive state
project membership, if available
```

5. excludes project conversations;
6. groups ordinary conversations by month of `update_time`;
7. prints a summary.

For example:

```text
2026-10   43
2026-09  187
2026-08  104
2026-07   91
2026-06   72
2026-05   55
2026-04   61
...
2024-01   19
```

This phase must make **no modifications**.

The purpose is to understand the data and choose sensible archive criteria.

---

## Phase 2 — filtering and dry runs

Add:

```text
--before
--older-than
--exclude
```

Print exactly what would be affected.

Still perform no mutation.

---

## Phase 3 — archiving

Implement the archive mutation with:

```text
--apply
```

Before making the first mutation:

1. generate the complete selection;
2. write the manifest;
3. confirm that every selected conversation is non-project;
4. begin requests.

Do not generate the selection lazily while archiving.

The complete mutation set should be fixed before the operation starts.

---

## Phase 4 — undo

Implement:

```text
--undo MANIFEST
```

Use the same underlying mutation mechanism to set:

```json
{
  "is_archived": false
}
```

or whatever the current ChatGPT UI uses.

---

# Rate limiting and reliability

This should be gentle with ChatGPT's backend.

Do not fire hundreds of simultaneous PATCH requests.

Something like one request at a time, or a very small concurrency level, is fine.

Handle:

```text
429
500
502
503
504
```

with bounded retries and exponential backoff.

A run involving 1,000 conversations does not need to finish instantly.

Correctness is more important than speed.

---

# Suggested language

Python is preferred for the final CLI.

A simple structure might be:

```text
chatgpt_archiver/
    api.py
    models.py
    selection.py
    manifest.py
    cli.py

tests/
```

Dependencies should be minimal.

Possibly:

```text
httpx
typer
rich
```

but use standard library equivalents where they are adequate.

A single-file prototype is completely acceptable initially.

---

# CLI examples

Read-only overview:

```bash
chatgpt-archive stats
```

Dry run:

```bash
chatgpt-archive archive --older-than 90d
```

Explicit cutoff:

```bash
chatgpt-archive archive --before 2026-07-01
```

Exclude conversations whose titles match:

```bash
chatgpt-archive archive \
  --older-than 90d \
  --exclude 'Discord|Home server'
```

Actually archive:

```bash
chatgpt-archive archive \
  --older-than 90d \
  --apply
```

Undo:

```bash
chatgpt-archive undo archive-run-2026-10-07T172000Z.json
```

The precise CLI design is flexible; these are examples rather than hard requirements.

---

# Important non-goals

Do not:

- delete conversations;
- modify conversation contents;
- archive project chats;
- require a browser extension;
- store permanent ChatGPT credentials;
- scrape or download the full contents of every conversation unnecessarily;
- make large concurrent request bursts;
- turn this into a hosted service.

We only need metadata sufficient to identify and archive conversations.

---

# Privacy

The tool should operate entirely locally.

Do not transmit conversation metadata to a third-party service.

Titles and conversation IDs should only exist:

- in memory;
- in the local manifest;
- in optional local logs.

Avoid retrieving full conversation message contents unless investigation proves it is unavoidable.

---

# Open questions to investigate

Before committing to implementation, determine:

1. What endpoint currently supplies the sidebar/history conversation list?
2. How does pagination work?
3. Is there a practical maximum page size?
4. What fields are returned for creation/update time?
5. How are project conversations identified?
6. Are project conversations excluded from the ordinary conversation listing, or merely annotated?
7. What operation does the current UI use for Archive?
8. What operation does it use for Unarchive?
9. How is authentication performed?
10. Does a session credential work cleanly from a local process?
11. Are there CSRF/origin checks that make browser-context execution preferable?
12. What happens under rate limiting?
13. Does changing archive state immediately remove a conversation from the normal history endpoint?
14. Is there any starred/pinned metadata worth supporting?

Document findings before building around undocumented behavior.

---

# First deliverable

Do **not** start by implementing bulk archive.

The first deliverable should be a read-only prototype that can produce something like:

```text
ChatGPT conversation inventory
==============================

Active ordinary conversations: 1,284
Project conversations skipped:   126

By last activity:

2026-10   43
2026-09  187
2026-08  104
2026-07   91
2026-06   72
2026-05   55
...

Older than 30 days:   512
Older than 60 days:   731
Older than 90 days:   917
Older than 180 days: 1084
Older than 1 year:   1167
```

Also print a few representative conversations around each cutoff.

Once this inventory looks correct, we can decide on the real archive policy and add mutations.

The key design principle throughout is:

> **Make it difficult to accidentally archive something and trivial to determine exactly what the tool changed.**