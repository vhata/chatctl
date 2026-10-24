# ChatGPT web API findings

How the ChatGPT web app's internal endpoints behave, gathered with the
discovery kit in [`discovery/`](../discovery/README.md). chatctl code should
only depend on behaviour recorded here with evidence.

These are undocumented internal APIs and can change without notice. Date
every observation.

Do not paste tokens, titles or full conversation IDs into this file. Use
placeholders such as `<conversation-id>`. Keep account-specific figures
(conversation counts, histograms, ID prefixes) in the local probe report
rather than here.

## How these findings were gathered

- 2026-10-14, first run: discovery probe (report version 1) from the
  DevTools console of a logged-in chatgpt.com tab in a Chromium-based
  browser.
- 2026-10-14, Network tab: archived and then unarchived a throwaway
  conversation from the web UI, capturing each request's URL, method,
  status, payload and response. Clicked a project in the sidebar.
- 2026-10-14, second run: probe with boolean value counts and nested
  object summaries, run while the throwaway conversation was archived.
- 2026-10-14, local access check: one `curl` GET with the bearer token, as
  described in [`discovery/README.md`](../discovery/README.md).
- 2026-10-24, transport proof of concept: `discovery/transport_poc.py`
  paged the whole listing from a local process through `remaldi evaluate`
  in a logged-in chatgpt.com tab in Vivaldi, returning aggregate counts
  only (see [`discovery/README.md`](../discovery/README.md)).
- 2026-10-24, Network tab: the names (not values) of the request headers
  on the web UI's archive PATCH.

The probe reports are local and not committed.

## Questions

### 1. What endpoint supplies the sidebar/history conversation list?

Finding: `GET /backend-api/conversations?offset=N&limit=L&order=updated`
returns `{items, total, limit, offset}`. Each item carries conversation
metadata only; `mapping`, `current_node` and `snippet` are present but
null, so message contents are not fetched.

Evidence: probe 2026-10-14, every page returned HTTP 200 with those four
top-level keys.

Fields observed on every item: `id`, `title`, `create_time`, `update_time`,
`latest_assistant_turn_created_at`, `pinned_time`, `mapping`,
`current_node`, `conversation_template_id`, `gizmo_id`, `is_archived`,
`is_starred`, `is_temporary_chat`, `is_do_not_remember`, `memory_scope`,
`context_scopes`, `context_scopes_v2`, `workspace_id`, `async_status`,
`safe_urls`, `blocked_urls`, `conversation_origin`,
`trial_conversation_type`, `is_automation_conversation`, `snippet`,
`summary_metadata`, `sugar_item_id`, `sugar_item_visible`.

`title` was a string on every item; no null or missing title was seen.

### 2. How does pagination work?

Finding: offset and limit. `offset` in the response echoes the request.
`total` is not a true total: on every page except the last it is
`offset + limit + 1`, which reads as "at least one more"; on the last page
it equals `offset + len(items)`, the real count. A client should page until
`offset + len(items) >= total` or an empty page, and must not use the first
page's `total` as the size of the history.

Evidence: probe 2026-10-14. Successive pages reported `total` 101, 201, 301
and so on with full pages of 100, and the final short page reported a total
equal to its offset plus its item count. The transport proof of concept
2026-10-24 saw the same pattern on every page, and every response echoed
the requested `offset`.

### 3. Is there a practical maximum page size?

Finding: `limit=100` is honoured (full pages of 100, `limit: 100` echoed).
Larger values have not been tried.

Evidence: probe 2026-10-14.

### 4. What fields are returned for creation/update time?

Finding: `create_time` and `update_time`, both ISO 8601 strings, present on
every item. Both are in UTC with a trailing `Z`; none had a numeric offset
and none lacked a zone. `create_time` always had fractional seconds;
`update_time` had them on most items but not all, so a parser must accept
both forms. `pinned_time` and `latest_assistant_turn_created_at` also exist
and were null on every item.

Evidence: probe 2026-10-14, timestamp format counts were 100% `iso8601`
for both fields (the probe checks only the date prefix); transport proof
of concept 2026-10-24, which counted the shape of each value (trailing
`Z`, numeric offset or none; fractional seconds or not) without returning
the values.

### 5. How are project conversations identified?

Finding: by `gizmo_id`. Project conversations have a `gizmo_id` beginning
`g-p-`. A `gizmo_id` beginning `g-` without `-p-` is taken to be a custom
GPT conversation, which is not a project; that reading comes from the ID
scheme, not from checking those conversations one by one, and the skip
rule does not depend on it. Ordinary conversations have `gizmo_id: null`.
`conversation_template_id` is non-null on exactly the items whose
`gizmo_id` is non-null, project and custom GPT conversations alike, and
null on every other item.
`workspace_id` was null on every item.

Projects are listed by `GET /backend-api/gizmos/snorlax/sidebar`, which
returns `{items, cursor}`: each item has `gizmo`, `tools`, `files`,
`product_features`, `has_tpp_conversation`, `project_file_limits` and
`project_connector_scope_limits`. A non-empty `cursor` means it is
cursor-paginated; the first page did not include every project referenced
by conversations, so either later pages or deleted projects account for the
rest.

The `gizmo` object has 40 fields, including `id`, `gizmo_type` (a
7-character string on every project, consistent with `snorlax`),
`display`, `instructions`, `created_at`, `updated_at`,
`last_interacted_at`, `num_interactions`, `is_archived`, `archived_at`,
`memory_enabled` and `memory_scope`. It does not list the project's
conversations.

The web UI loads the sidebar with
`GET /backend-api/gizmos/snorlax/sidebar?conversations_per_gizmo=5&limit=...`
when the page loads, which presumably embeds each project's most recent
conversations. Expanding or collapsing a project in the sidebar makes no
request.

Evidence: probe 2026-10-14 (both runs), value distribution of `gizmo_id`
(prefixes only), the projects probe's nested summary of `gizmo`, and the
Network tab list on page load; transport proof of concept 2026-10-24,
which counted items with both fields non-null, each one alone, and
neither, and found only "both" and "neither".

### 6. Are project conversations excluded from the ordinary conversation listing, or merely annotated?

Finding: annotated, not excluded. The ordinary listing includes project
and custom GPT conversations alongside ordinary ones, so chatctl has to
filter on `gizmo_id` itself (rule in [`AGENTS.md`](../AGENTS.md#rules)).

Evidence: probe 2026-10-14, non-null `gizmo_id` values with the `g-p-`
prefix appeared in `/backend-api/conversations` results.

### 7. What operation does the current UI use for Archive?

Finding: `PATCH /backend-api/conversation/<conversation-id>` (singular
`conversation`) with the JSON body `{"is_archived": true}`. The response is
HTTP 200 with `{"success": true}`.

Evidence: Network tab 2026-10-14, archiving a throwaway conversation from
its sidebar menu.

### 8. What operation does it use for Unarchive?

Finding: the same request with `{"is_archived": false}`. The response is
HTTP 200 with `{"success": true}`.

Evidence: Network tab 2026-10-14, restoring the throwaway conversation from
Settings, Data controls, Archived chats.

### 9. How is authentication performed?

Finding: `GET /api/auth/session` (cookie-authenticated) returns an
`accessToken`, which is sent as `Authorization: Bearer <token>` to
`/backend-api/...`. This works from the page's own origin. The session
response also includes `sessionToken`, `expires`, `user`, `account` and a
`WARNING_BANNER` string; `sessionToken` is at least as sensitive as the
access token.

Evidence: probe 2026-10-14, all `/backend-api` GETs with the bearer token
returned 200.

### 10. Does a session credential work cleanly from a local process?

Finding: not with a plain HTTP client carrying only the token. A `curl`
GET to `/backend-api/conversations` with a freshly copied bearer token and
curl's default headers returned HTTP 403 with `server: cloudflare` and
`cf-mitigated: challenge`: Cloudflare's bot check stopped the request
before it reached the API, so the token itself was never tested. Adding
the session cookies, a browser `User-Agent` or a browser-like TLS client
has not been tried. Requests made from the logged-in page succeed, so
running inside a real browser session is the only route known to work.

A local process can drive such a session over the DevTools protocol:
evaluating JavaScript in a logged-in chatgpt.com tab with
`remaldi evaluate --await-promise --return-by-value`, where the script
fetches `/api/auth/session` and then one listing page with the page's own
`fetch`, paged the whole listing with Python running the loop. Every
evaluation returned HTTP 200 for both requests, with no retries; each
took roughly one to three and a half seconds, including the session
fetch. The choice of transport is recorded in
[`DECISIONS.md`](DECISIONS.md).

Evidence: local access check 2026-10-14, output
`403 server=cloudflare cf-mitigated=challenge`; transport proof of
concept 2026-10-24.

### 11. Are there CSRF/origin checks that make browser-context execution preferable?

Finding: for GETs, none observed. The probe's GETs from the page's origin
succeed with only the `Authorization` header added.

For the archive PATCH, the UI sends these headers. The browser adds the
following to any `fetch` from the page: `accept-language`, `origin`,
`priority`, `referer`, `sec-ch-ua`, `sec-ch-ua-mobile`,
`sec-ch-ua-platform`, `sec-fetch-dest`, `sec-fetch-mode`,
`sec-fetch-site` and `user-agent`. The web app sets the rest: `accept`,
`authorization`, `chatgpt-account-id`, `content-type`, `oai-device-id`,
`oai-did`, `oai-language`, `originator`, `x-openai-codex-window-type`,
`x-openai-rate-limit-join-workspace` and `x-openai-web-frontend`. None is
named like a CSRF or sentinel token, but the device and account headers
could be checked. Whether a PATCH from the page carrying only
`Authorization` and `Content-Type` is accepted is still open; no code may
send a PATCH until it is answered.

Outside the browser, Cloudflare's bot challenge blocks requests before
any application-level check could apply (see question 10).

Evidence: probe 2026-10-14; Network tab 2026-10-14 and 2026-10-24
(header names only); local access check 2026-10-14.

### 12. What happens under rate limiting?

Finding: not observed. The probe's sequential GETs with a 500 ms pause
between pages, run twice, received no 429s, and neither did the transport
proof of concept, which paged the whole listing the same way with a
session fetch before each page. The UI's archive and unarchive requests
succeeded first time.

Evidence: probe 2026-10-14 (both runs); Network tab 2026-10-14; transport
proof of concept 2026-10-24.

### 13. Does changing archive state immediately remove a conversation from the normal history endpoint?

Finding: yes. The default listing excludes archived conversations
entirely: every item it returned had `is_archived: false`, and every item
from `GET /backend-api/conversations?is_archived=true` had
`is_archived: true`. An archived conversation leaves the web UI's sidebar
straight away, without a reload, and appeared in the archived listing in a
probe run moments later. Whether it stayed out of the sidebar after a
page reload was not recorded.

Evidence: Network tab and second probe run 2026-10-14, with the throwaway
conversation archived.

### 14. Is there any starred/pinned metadata worth supporting?

Finding: `is_starred` exists (null on most items, `false` on a few, `true`
on none in the observed account) and `pinned_time` exists (null on every
item). Either is a candidate for a `--keep-starred` style exclusion, but
neither is in use in the observed account. No star or pin request was
captured, so how the UI sets them is not known.

`is_automation_conversation` is `true` on some items. These are likely
conversations created by scheduled tasks, and are a candidate for an
exclusion option.

Evidence: probe 2026-10-14 (second run, boolean value counts).

## Other observations

- With an ad blocker active, the ChatGPT page logs failed POSTs to
  `/ces/v1/rgstr` (its Statsig analytics) in the console while the probe
  runs. They are the page's own requests, not the probe's.
