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
- 2026-10-24, user-reported minimal-PATCH test: one throwaway conversation
  archived through the page's wrapped `fetch`, with conflicting results
  in the two listings and the sidebar (questions 11 and 13). No new
  account experiment was run for the 2026-10-26 investigation.

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
every item. Both were in UTC with a trailing `Z`; none had a numeric offset
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
`conversation_template_id` was non-null on exactly the items whose
`gizmo_id` was non-null, project and custom GPT conversations alike, and
null on every other item (2026-10-24).
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

This records the UI operation only. Unarchive through a direct page
`fetch` has not been demonstrated, nor has a reliable listing-based
restoration check (see question 13).

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
`remaldi` call took roughly one to three seconds, including the session
fetch and remaldi's own overhead. The choice of transport is recorded in
[`DECISIONS.md`](DECISIONS.md).

Evidence: local access check 2026-10-14, output
`403 server=cloudflare cf-mitigated=challenge`; transport proof of
concept 2026-10-24.

### 11. Are there CSRF/origin checks that make browser-context execution preferable?

Finding: for GETs, none observed. The probe's GETs from the page's origin
succeed with only the `Authorization` header added.

For the archive PATCH, the captured request headers were the names
below (names only; the capture lists no `cookie` or `accept-encoding`).
The browser adds these to a `fetch` like this one from the page:
`accept-language`, `origin`, `priority`, `referer`, `sec-ch-ua`,
`sec-ch-ua-mobile`, `sec-ch-ua-platform`, `sec-fetch-dest`,
`sec-fetch-mode`, `sec-fetch-site` and `user-agent`. `accept` and
`content-type` are set either by the web app or by the browser's
defaults; the names alone do not say which. The web app sets the rest:
`authorization`, `chatgpt-account-id`, `oai-device-id`, `oai-did`,
`oai-language`, `originator`, `x-openai-codex-window-type`,
`x-openai-rate-limit-join-workspace` and `x-openai-web-frontend`. None is
named like a CSRF or sentinel token, but the device and account headers
could be checked.

On 2026-10-24, the user sent one archive PATCH through the page's wrapped,
non-native `fetch`, setting only `Authorization` and `Content-Type` at the
call site. It returned HTTP 200 with `{"success": true}`. The target
appeared in the archived listing and Settings, Archived chats, but also
remained in the default listing and a freshly loaded sidebar (question
13). This demonstrates HTTP acceptance in that browser context, not a
verified archive postcondition or a request with only two app-set headers
on the wire: the wrapper may add headers. The actual outgoing header names
for that direct request were not recorded here. An equivalent direct
unarchive result was not reported.

The remaining questions are which headers the intended transport actually
sends and needs, and how to verify durable archive and restore state.
Product mutation code remains blocked by the gates under question 13;
the user-run experiment below starts with GETs and UI controls rather
than another direct PATCH.

Outside the browser, Cloudflare's bot challenge blocks requests before
any application-level check could apply (see question 10).

Evidence: probe 2026-10-14; Network tab 2026-10-14 and 2026-10-24
(UI header names only); local access check 2026-10-14; user's minimal-PATCH
test recorded in `TODO.md`, 2026-10-24.

### 12. What happens under rate limiting?

Finding: not observed. The probe's sequential GETs with a 500 ms pause
between pages, run twice, received no 429s, and neither did the transport
proof of concept, which paged the whole listing the same way with a
session fetch before each page. The UI's archive and unarchive requests
succeeded first time.

Evidence: probe 2026-10-14 (both runs); Network tab 2026-10-14; transport
proof of concept 2026-10-24.

### 13. Does changing archive state immediately remove a conversation from the normal history endpoint?

Finding: the observations disagree; immediate removal is not a validated
guarantee for a direct PATCH.

- **UI archive, 2026-10-14:** every item in the default listing had
  `is_archived: false`, and every item in the sampled archived listing had
  `is_archived: true`. The throwaway left the sidebar immediately and
  appeared in the archived listing in the probe run moments later.
  Sidebar persistence after reload was not recorded. The probe reads only
  the first archived page, so its sample cannot establish target absence.
- **Direct wrapped-fetch archive, 2026-10-24:** the PATCH returned HTTP 200
  with `{"success": true}`. The same throwaway appeared in the archived
  listing with `is_archived: true` and in Settings, Archived chats, but
  also in the default listing with `is_archived: false` and a different
  `update_time`. It remained in the sidebar after a fresh load in a new
  tab. The elapsed time to those checks and eventual convergence were
  not recorded.

Neither observation establishes which listing is authoritative, a
convergence bound, the cause of disagreement, or the sufficiency of the
direct request. Delayed indexing, caching, request context and additional
UI effects are hypotheses, not findings. A success response alone does
not establish that the conversation left active history. A later
`update_time` alone does not establish which state is correct.

Evidence: Network tab and second probe run 2026-10-14; user's minimal-PATCH
test recorded in `TODO.md`, 2026-10-24. The transport proof of concept
validated read-only pagination, not mutation consistency.

The focused [user-run experiment](../discovery/patch-listing-experiment.md)
first rechecks the original throwaway without mutation, then compares a
second throwaway archived and unarchived through the UI. It records
complete-list evidence and actual request header names. Results are
pending; no account was accessed during preparation.

#### Mutation gates

`archive --apply` remains blocked until evidence establishes:

1. A preflight rule for distinguishing active conversations from
   already-archived conversations, including conflicting or incomplete
   listing results. A stale `false` must not make a pre-existing archive
   look like a change owned by a new run.
2. A verified archive postcondition and bounded readback policy for both
   acknowledged and unknown transport outcomes. Disagreement stays
   unknown; do not replay a PATCH or mark success from either listing or
   the HTTP acknowledgement alone.
3. The intended request context and any required UI side effects, with
   actual wire-header evidence rather than caller-header assumptions.

`undo` additionally remains blocked until evidence establishes:

1. Direct unarchive through the intended transport and a verified restore
   postcondition, including conflicting listings and unknown outcomes.
2. A manifest rule tying each restore to a confirmed change owned by that
   run, with its pre-change state. Pre-existing archives and uncertain
   changes must not become automatic undo candidates.

The manifest must preserve unresolved outcomes for manual reconciliation;
re-reading an unvalidated state source does not resolve them. The client,
dry run and manifest implementation dependencies remain in
[`TODO.md`](../TODO.md). These gates do not block read-only client work.

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
