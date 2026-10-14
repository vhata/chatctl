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

- 2026-10-14: discovery probe (report version 1) run from the DevTools
  console of a logged-in chatgpt.com tab in a Chromium-based browser. The
  report itself is local and not committed.
- Still to do: the Network tab checklist in
  [`discovery/README.md`](../discovery/README.md), the local access check
  in the same file, and a second probe run with the report additions made
  after the first run (boolean value counts, nested object summaries).

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

### 2. How does pagination work?

Finding: offset and limit. `offset` in the response echoes the request.
`total` is not a true total: on every page except the last it is
`offset + limit + 1`, which reads as "at least one more"; on the last page
it equals `offset + len(items)`, the real count. A client should page until
`offset + len(items) >= total` or an empty page, and must not use the first
page's `total` as the size of the history.

Evidence: probe 2026-10-14. Successive pages reported `total` 101, 201, 301
and so on with full pages of 100, and the final short page reported a total
equal to its offset plus its item count.

### 3. Is there a practical maximum page size?

Finding: `limit=100` is honoured (full pages of 100, `limit: 100` echoed).
Larger values have not been tried.

Evidence: probe 2026-10-14.

### 4. What fields are returned for creation/update time?

Finding: `create_time` and `update_time`, both ISO 8601 strings, present on
every item. `pinned_time` and `latest_assistant_turn_created_at` also exist
and were null on every item.

Evidence: probe 2026-10-14, timestamp format counts were 100% `iso8601`
for both fields.

### 5. How are project conversations identified?

Finding: by `gizmo_id`. Project conversations have a `gizmo_id` beginning
`g-p-`. A `gizmo_id` beginning `g-` without `-p-` is a custom GPT
conversation, which is not a project. Ordinary conversations have
`gizmo_id: null`. `conversation_template_id` was non-null on exactly the
same items as `gizmo_id`. `workspace_id` was null on every item.

Projects are listed by `GET /backend-api/gizmos/snorlax/sidebar`, which
returns `{items, cursor}`: each item has `gizmo` (a large object describing
the project), `tools`, `files`, `product_features`,
`has_tpp_conversation`, `project_file_limits` and
`project_connector_scope_limits`. A non-empty `cursor` means it is
cursor-paginated; the first page did not include every project referenced
by conversations, so either later pages or deleted projects account for the
rest.

Evidence: probe 2026-10-14, value distribution of `gizmo_id` (prefixes
only) and the projects probe.

Open: the fields of the sidebar's `gizmo` object (the first report only
showed its key count) and how the sidebar lists a project's conversations.

### 6. Are project conversations excluded from the ordinary conversation listing, or merely annotated?

Finding: annotated, not excluded. The ordinary listing includes project
and custom GPT conversations alongside ordinary ones. chatctl must filter
on `gizmo_id` itself.

Evidence: probe 2026-10-14, non-null `gizmo_id` values with the `g-p-`
prefix appeared in `/backend-api/conversations` results.

### 7. What operation does the current UI use for Archive?

Finding:

Evidence:

### 8. What operation does it use for Unarchive?

Finding:

Evidence:

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

Finding:

Evidence:

### 11. Are there CSRF/origin checks that make browser-context execution preferable?

Finding: none needed for GETs from the page's origin. Unknown for
mutations and for requests from outside the browser.

Evidence: probe 2026-10-14 sent only the `Authorization` header.

### 12. What happens under rate limiting?

Finding: not observed. The probe's sequential GETs with a 500 ms pause
between pages received no 429s.

Evidence: probe 2026-10-14.

### 13. Does changing archive state immediately remove a conversation from the normal history endpoint?

Finding: `GET /backend-api/conversations?is_archived=true` lists archived
conversations, and items carry an `is_archived` boolean. Whether the
default listing excludes archived conversations, and how quickly a change
shows up, is not yet known.

Evidence: probe 2026-10-14, archived listing returned HTTP 200 with
`is_archived: true` samples.

### 14. Is there any starred/pinned metadata worth supporting?

Finding: `is_starred` (null on most items, boolean on a few) and
`pinned_time` (null on every item) exist. Either is a candidate for a
`--keep-starred` style exclusion.

Evidence: probe 2026-10-14.

## Other observations

- With an ad blocker active, the ChatGPT page logs failed POSTs to
  `/ces/v1/rgstr` (its Statsig analytics) in the console while the probe
  runs. They are the page's own requests, not the probe's.
