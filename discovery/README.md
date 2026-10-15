# Discovery kit

chatctl depends on internal, undocumented endpoints of the ChatGPT web app.
This kit answers the open questions in
[`docs/api-findings.md`](../docs/api-findings.md) using your own logged-in
browser session, before any chatctl code relies on them.

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
4. `GET /backend-api/gizmos/snorlax/sidebar`, which is believed to list
   projects.

These paths started as educated guesses; the 2026-10-14 runs confirmed
them (see [`docs/api-findings.md`](../docs/api-findings.md)). If a probe
comes back with an error or an unexpected shape, open the Network tab, filter by `backend-api`, reload the
page, find the request the sidebar actually makes, and edit the `ENDPOINTS`
constant at the top of `probe.js`.

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
  example the fields of each project's `gizmo` object). Objects keyed by
  IDs are reported only by key count and never descended into.
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
   again. This shows whether the ordinary listing ever contains archived
   conversations (`is_archived` true/false counts), whether the archived
   listing picked up the throwaway chat, and the fields of each project's
   `gizmo` object.
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

2. In a terminal (bash or zsh), run the following. At the first line, paste
   the token and press Enter; nothing is echoed and it does not reach your
   history.

   ```bash
   read -rs CHATGPT_TOKEN
   curl -sS -o /dev/null \
     -w '%{http_code} server=%header{server} cf-mitigated=%header{cf-mitigated}\n' \
     -H @<(printf 'Authorization: Bearer %s\n' "$CHATGPT_TOKEN") \
     'https://chatgpt.com/backend-api/conversations?offset=0&limit=1&order=updated'
   unset CHATGPT_TOKEN
   pbcopy < /dev/null
   ```

   The header is passed through a process substitution so the token does
   not appear in the process list. `pbcopy < /dev/null` clears the macOS
   clipboard.

3. Record the output line. `200` means the token works from a local
   process. `401` means it was rejected. `403` together with
   `cf-mitigated=challenge` means a bot check blocked the request, which
   would favour running chatctl's requests from the browser.

Record the answers in [`docs/api-findings.md`](../docs/api-findings.md).

## Privacy

Probe reports, HAR exports and copied requests contain account metadata.
`.gitignore` excludes `chatctl-probe-*.json` and `*.har`. Keep other copies
out of the repository too. When writing up findings, replace conversation
IDs and titles with placeholders such as `<conversation-id>`, and never
include tokens. Keep account-specific counts in the local report rather
than in committed docs.
