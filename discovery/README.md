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

These paths are educated guesses. If a probe comes back with an error or an
unexpected shape, open the Network tab, filter by `backend-api`, reload the
page, find the request the sidebar actually makes, and edit the `ENDPOINTS`
constant at the top of `probe.js`.

### What the report contains

- Field names, their types and how often each appears.
- The encoding of timestamp fields (ISO 8601, epoch seconds or epoch
  milliseconds).
- Distinct values of fields that look project-related, truncated to 8
  characters.
- Pagination fields and the page size the server actually used.
- Conversation counts by month of `update_time` and `create_time`, and
  counts older than 30, 60, 90, 180 and 365 days.
- Up to three redacted sample items: titles reduced to their length, IDs
  truncated to 8 characters, other strings reduced to their length.

It does not contain titles, full conversation IDs, message content, the
session's user details or the access token.

## Network tab checklist

Some questions can only be answered by watching the web app make a change.
Use a throwaway conversation for this: start a new chat and send "test".

In DevTools, open the Network tab, filter by `backend-api` and enable
"Preserve log". For each request worth recording, note the method, the
path, the request body, the response status and the top-level response
keys. Note the names of any unusual request headers (anything mentioning
CSRF, origin, device or sentinel). Never copy the `Authorization` value.

1. **Archive.** Archive the throwaway chat from its sidebar menu and record
   the request.
2. **Visibility.** Check whether the chat disappears from the sidebar
   straight away and after a reload. Rerun the probe and check whether it
   now appears in the archived listing.
3. **Unarchive.** Restore the chat from wherever the UI lists archived chats
   (currently under Settings) and record the request.
4. **Projects.** Open a project and record the requests that list its
   conversations: path, pagination parameters and top-level response keys.
   Compare with the probe's project-related field values to see whether
   project conversations also appear in the ordinary conversation list.
5. **Rate limiting.** Note any 429 responses and any `Retry-After` header.
6. **Starred or pinned.** If the UI lets you pin or star a conversation, note
   which field changes.

Record the answers in [`docs/api-findings.md`](../docs/api-findings.md).

## Privacy

Probe reports, HAR exports and copied requests contain account metadata.
`.gitignore` excludes `chatctl-probe-*.json` and `*.har`. Keep other copies
out of the repository too. When writing up findings, replace conversation
IDs and titles with placeholders such as `<conversation-id>`, and never
include tokens.
