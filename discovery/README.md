# Discovery kit

chatctl depends on internal, undocumented endpoints of the ChatGPT web app.
This kit answers the open questions in
[`docs/api-findings.md`](../docs/api-findings.md) using your own logged-in
browser session, before any chatctl code relies on them.

For the conflicting direct-PATCH archive results, use the focused
[listing disagreement experiment](patch-listing-experiment.md). Its
GET-only [checker](listing_check.js) tracks two local target aliases
through both complete listings. The general probe below samples only the
first archived page and cannot establish a particular target's absence.

## Running the probe

1. Open <https://chatgpt.com> in a desktop browser and make sure you are
   logged in.
2. Open DevTools (Cmd+Option+I on macOS, F12 elsewhere) and switch to the
   Console tab.
3. Paste the whole of [`probe.js`](probe.js) and press Enter. Chrome may ask
   you to type `allow pasting` first.
4. Wait. The probe fetches one page of conversations at a time with a
   half-second pause between pages and logs progress as it goes. A long
   history takes a few minutes.
5. When it finishes, the browser downloads
   `chatctl-probe-<timestamp>.json` and the console prints a short summary.

### What it does

All requests are GETs, made through a single helper:

1. `GET /api/auth/session` to obtain the access token the web app uses. The
   token is held in memory only.
2. `GET /backend-api/conversations?offset=N&limit=L&order=updated`, page by
   page, until an empty page, the reported total, a page with nothing new,
   an error, or 200 pages.
3. The first page of the same endpoint with `is_archived=true`.
4. `GET /backend-api/gizmos/snorlax/sidebar`, which lists projects.

These paths started as educated guesses; the 2026-10-14 runs confirmed
them (see [`docs/api-findings.md`](../docs/api-findings.md)). If a probe
comes back with an error or an unexpected shape, open the Network tab,
filter by `backend-api`, reload the page, find the request the sidebar
actually makes, and edit the `ENDPOINTS` constant at the top of
`probe.js`.

### What the report contains

- Field names, their types and how often each appears.
- True/false counts for boolean fields such as `is_archived` and
  `is_starred`.
- The encoding of timestamp fields (ISO 8601, epoch seconds or epoch
  milliseconds).
- Distinct values of fields that look project-related. ID fields (names
  ending in `id`) keep their first 8 characters; any other value is reduced
  to its type and length, since it could be a project name.
- For object-valued fields, the same field summary one level down (for
  example the fields of each project's `gizmo` object). This is limited
  to objects whose keys look like the API's own lower-case field names
  and that have at most 60 keys; wider objects are not descended into.
  Past 80 distinct keys across all items, the keys are counted, not
  listed. The test is a heuristic: it keeps out maps keyed by IDs and
  capitalised or numbered keys, but a short lower-case key holding user
  text would get through.
- Pagination fields and the page size the server actually used.
- Conversation counts by month of `update_time` and `create_time`, and
  counts older than 30, 60, 90, 180 and 365 days.
- Up to three redacted sample items: titles reduced to their length, IDs
  truncated to 8 characters, other strings reduced to their length.

It does not contain titles, full conversation IDs, message content, the
session's user details or the access token.

With an ad blocker active, the console also shows failed POSTs to
`/ces/v1/rgstr`. Those are the ChatGPT page's own analytics requests being
blocked, not the probe's.

## Network tab checklist

Some questions can only be answered by watching the web app make a change.
Use a throwaway conversation: start a new chat and send "test".

Set up DevTools first: open the Network tab, type `backend-api` in the
filter box, and tick "Preserve log". When a step says to capture a request,
click it in the list and record:

- **Headers tab:** the request URL, method and status code, and the *names*
  of the request headers. Never record the values of `Authorization` or
  `Cookie`. Note any header whose name mentions CSRF, origin, device,
  sentinel or account.
- **Payload tab:** the request body, if there is one.
- **Response tab:** the shape of the response (its top-level keys).

Screenshots are fine as long as the `Authorization` and `Cookie` lines are
covered. Do not use "Copy as cURL" or "Copy as fetch" unless you remove the
token and cookies from the copy, since both include them.

1. **Archive.** Archive the throwaway chat from its menu in the sidebar.
   Capture the request this makes.
2. **Visibility.** Note whether the chat leaves the sidebar straight away,
   and whether it stays gone after a reload.
3. **Second probe run.** While the chat is still archived, run `probe.js`
   again. This records archive-flag counts and a sample of the archived
   listing, plus the fields of each project's `gizmo` object. Counts and
   samples cannot establish which listing contains a specific throwaway;
   use the focused checker above for that comparison.
4. **Unarchive.** Restore the chat from the archived chats list (currently
   Settings, then Data controls, then Archived chats) and capture the
   request.
5. **Star.** If the chat menu offers a star or pin option, use it on the
   throwaway chat, capture the request, then undo it.
6. **Projects.** Reload the page and capture the `sidebar?...` request,
   which loads projects and their recent conversations. Expanding or
   collapsing a project in the sidebar makes no request.
7. **Rate limiting.** Note any request that returned 429, and its
   `Retry-After` header if present.

Delete the throwaway chat afterwards if you like.

## Local access check

This answers whether the token works from outside the browser (question 10
in `docs/api-findings.md`). It makes one read-only request for a single
conversation and prints only the HTTP status and two response headers, not
the response body.

The access token is effectively an account credential until it expires.
Do not paste it into chats, files or shell history.

1. In the DevTools console on chatgpt.com, copy the token to the
   clipboard:

   ```js
   copy((await (await fetch("/api/auth/session")).json()).accessToken)
   ```

2. In a terminal (bash or zsh), run this line on its own, then paste the
   token and press Enter. Nothing is echoed and the token does not reach
   your history.

   ```bash
   read -rs CHATGPT_TOKEN
   ```

   Run it by itself rather than pasting it together with the next block:
   without bracketed paste (macOS's `/bin/bash` 3.2, some terminal and
   tmux setups), `read` would take the next pasted line as the token, and
   the token pasted afterwards would run as a command and land in your
   history.

3. Then run the request. It needs curl 7.84 or later for `%header{...}`.

   ```bash
   curl -sS -o /dev/null \
     -w '%{http_code} server=%header{server} cf-mitigated=%header{cf-mitigated}\n' \
     -H @<(printf 'Authorization: Bearer %s\n' "$CHATGPT_TOKEN") \
     'https://chatgpt.com/backend-api/conversations?offset=0&limit=1&order=updated'
   unset CHATGPT_TOKEN
   pbcopy < /dev/null
   ```

   The header is passed through a process substitution so the token does
   not appear in the process list. `pbcopy < /dev/null` clears the macOS
   clipboard, but not copies kept by a clipboard manager or synced by
   Universal Clipboard; clear those separately if you use them.

4. Record the output line. `200` means the token works from a local
   process. `401` means it was rejected. `403` together with
   `cf-mitigated=challenge` means a bot check blocked the request, which
   would favour running chatctl's requests from the browser.

Record the answers in [`docs/api-findings.md`](../docs/api-findings.md).

## Transport proof of concept

[`transport_poc.py`](transport_poc.py) tests whether chatctl can reach
the API from a local process by evaluating JavaScript in an open,
logged-in chatgpt.com tab over the DevTools protocol, using
[remaldi](https://github.com/vhata/remaldi) and Vivaldi. It pages the
whole conversation listing that way, with Python running the loop, and
prints a summary. It is read-only and writes no files.

### Prerequisites

- `remaldi` on your `PATH` (or pass `--remaldi /path/to/remaldi`). It
  starts its own background service on first use; there is no need to
  run `remaldi serve`.
- Vivaldi running with the debugging port open. Quit Vivaldi completely,
  then start it with:

  ```bash
  open -a Vivaldi --args --remote-debugging-port=9222
  ```

  An ordinary launch, or a relaunch after an update, leaves the port
  closed. While it is open, any local process can control the browser,
  so quit and relaunch normally when you are done. `remaldi stop` stops
  remaldi's service.
- Exactly one chatgpt.com tab open, logged in. The script finds it in the
  browser's local target list (`http://127.0.0.1:9222/json/list`, or
  `$REMALDI_ENDPOINT`). With several chatgpt.com tabs, close the extras or
  pass `--target` with the tab's DevTools target ID, the `id` field of
  its entry in that list. remaldi matches the ID exactly; it does not
  match URLs, and without a target it evaluates in Vivaldi's own UI
  rather than in a tab.
- Keep that tab in the foreground while the script runs, and make sure
  it is not hibernated. The browser throttles timers in background tabs
  and does not run scripts in hibernated ones, which would show up as
  timeouts.

### Running it

From the repository root:

```bash
uv run python discovery/transport_poc.py
```

or, naming the tab:

```bash
uv run python discovery/transport_poc.py --target <target-id>
```

`--max-pages N` stops after N pages (default 200).

For each page it runs one `remaldi evaluate --await-promise
--return-by-value` in the tab. The evaluated script checks that the tab is
on `https://chatgpt.com`, fetches `/api/auth/session` for the access
token, then fetches one page of
`/backend-api/conversations?offset=N&limit=100&order=updated` with it.
Both are GETs, made through a single helper. The script returns only the
HTTP status, the response's top-level keys, `total`, `offset`, `limit`,
the number of items and aggregate counts; the token never leaves the tab.

Requests go one at a time, with half a second between pages. On a 429,
a 5xx or a timeout the page is retried up to three times, after 2, 4 and
8 seconds or the server's `Retry-After` if longer (capped at 60). Any
other error stops the run. The page script abandons its own requests
after 4 seconds, before remaldi's 5-second limit. When remaldi cannot
say whether an evaluation ran, the retry waits at least 5 seconds, so
that a late-starting evaluation has finished first; a tab that delays
running the script could still let two requests overlap briefly.

It stops when a page is empty or when `offset + items >= total`, the
rule recorded under question 2 in
[`docs/api-findings.md`](../docs/api-findings.md). It also stops, as an
error, if a response's `offset` differs from the one requested, since
that would mean the server is not paging as recorded.

### What to paste back

Progress goes to stderr, one line per page (offset, item count, reported
total, timing). The summary goes to stdout:

- `stop`: why it stopped (`reached_total` or `empty_page` is a clean
  finish) and the number of pages.
- `items` and `last reported total`.
- `question 2 pattern`: whether every page but the last reported
  `offset + limit + 1` and the last reported the real count.
- `offset echoed`: how many pages echoed the requested offset.
- `top-level keys` of the listing responses.
- `gizmo_id`: `null`, `project_prefix` (`g-p-`), `other_string`,
  `other_type` or `missing`.
- `gizmo_and_template`: whether `gizmo_id` and `conversation_template_id`
  are non-null on the same items: `both`, `gizmo_id_only`,
  `template_id_only` or `neither`.
- `is_archived`: `true`, `false`, `null`, `other_type` or `missing`.
- `update_time` and `create_time`: the shape of each timestamp, never
  its value. `z` ends in `Z`, `offset` has a numeric `+HH:MM` or
  `-HH:MM` offset, `no_offset` has neither, and `+fraction` marks
  fractional seconds; otherwise `null`, `missing`, `not_string` or
  `string_not_iso8601`.
- `title`: `string`, `null`, `other_type` or `missing`.
- `id`: `string`, `other` or `missing`.
- `retries`, `evaluations`, `elapsed` and `error`.

Paste the summary, any progress lines that mention a retry, and any
error. The counts are specific to your account: keep them out of
committed files, as with the probe report. The findings recorded in
`docs/api-findings.md` say what shape the listing has and whether the
transport works, not how many conversations you have.

## Privacy

Probe reports, HAR exports and copied requests contain account metadata.
`.gitignore` excludes `chatctl-probe-*.json` and `*.har`. Keep other copies
out of the repository too. When writing up findings, replace conversation
IDs and titles with placeholders such as `<conversation-id>`, and never
include tokens. Keep account-specific counts in the local report rather
than in committed docs.
