# Archive listing disagreement: user-run experiment

Prepared 2026-10-26. Results pending. Agents must not run this against an
account. The [dated evidence and mutation gates](../docs/api-findings.md#13-does-changing-archive-state-immediately-remove-a-conversation-from-the-normal-history-endpoint)
are authoritative; this file is the procedure for gathering more evidence.

The question is whether the original direct-PATCH result converges without
another mutation, and whether a contemporary UI archive behaves the same
way. We do not yet know which listing reflects durable state. A 200
`{"success": true}` response, Settings visibility or a newer `update_time`
does not answer that question.

## Setup

Use the same account and workspace as the original test, in a foreground
`https://chatgpt.com` tab. Keep other account activity idle during each
scan. In DevTools, open Network, enable **Preserve log** and **Disable
cache**. Capture all requests around the UI actions, then inspect the API
requests; filtering only for `conversation` or `PATCH` can hide another
operation. Do not export a HAR or copy requests into the repository.

Identify locally:

- **A:** the original throwaway archived through wrapped `fetch` on
  2026-10-24. Do not rearchive, unarchive or otherwise change A during the
  initial read-only phase. If its intervening history is unknown, record
  that; convergence cannot then be attributed to elapsed time alone.
- **B:** a separate ordinary throwaway for the UI control, with no project
  or custom GPT membership. Create it only after the initial A check if
  it does not already exist. Verify that the listing explicitly reports
  `gizmo_id: null`; a missing or set value means stop before UI mutation.

Keep IDs local. If A can no longer be identified, say so: B alone cannot
explain what happened to A. Do not substitute an important conversation.

Paste the whole of [listing_check.js](listing_check.js) into the Console.
It defines a function and makes no requests until you call it:

```js
await chatctlListingCheck()
```

Enter A's ID in the first prompt and B's in the optional second prompt.
Use the same aliases every run. Cancel A's prompt to stop; leaving B blank
or cancelling its prompt skips B. Reloading or opening a
new tab removes the helper; paste it again there. The function returns
only a redacted report. Keep reports locally, outside the repository.

The checker uses the tab's existing `fetch`, including its wrapper. It
does not replace it with a purported native implementation. All requests
are GETs: session, the full default listing, then the full archived
listing, at most 200 pages each, 100 items requested per page, one request
at a time with at least 500 ms between requests. Requests have a timeout;
errors stop the check without retries. Do not run another scan or the
general probe concurrently. Stop on authentication failures, 429s, 5xx,
unexpected shapes or timeouts; record the result and resume manually
later rather than repeatedly rerunning it.

`cache: "no-store"` and DevTools' cache setting control browser caching;
neither proves that a fetch wrapper, service worker or server cache was
bypassed. Note any Network indication of service-worker or cache use.

## Phase 1: original target, no mutation

1. Run the checker for A (leave B blank if needed). Record wall-clock time
   and any known intervening changes to A since the original test.
2. Wait about 30 seconds **after the scan finishes**, then run it again.
   Wait about two minutes after that scan finishes and run it once more.
   These are bounded observations, not a discovered convergence SLA.
   A long history makes the actual windows longer; retain scan timestamps.
3. Note A's sidebar and Settings, Archived chats, visibility locally.
   Open a fresh tab in the same account/workspace, check the sidebar and
   repeat one scan there. Keep only one scan active. Record which tab and
   whether cache or service-worker handling differed.

Each listing reports completion, a stop reason, pages and per-alias
presence/observations. A missing target is `absent` only when that scan
completed cleanly; otherwise it is `unknown`. A found row remains positive
evidence even if a later page fails. Keep duplicate/conflicting rows in
the report. Check each observation's archive flag and membership, rather
than treating mere presence in either endpoint as a state verdict.

`updateTimeEquality` compares target timestamps across the two listing
reads; it never prints their values. Different times show different
representations, not which is right. The scans happen sequentially and
are not an atomic snapshot. If the target moves during a scan, repeat
later with no activity before drawing a conclusion.

## Phase 2: contemporary UI control

1. Run A and B together for a baseline. B should be in the completed
   default scan, with `is_archived: false` and explicit `gizmo_id: null`,
   and absent from the completed archived scan. If not, stop and report
   the ambiguous baseline.
2. With Network recording, **archive B once using the web UI**. Note its
   immediate sidebar visibility and the action's time. Inspect every
   request around the action, including any extra writes, not just the
   visible archive PATCH. Do not replay any request.
3. Run the checker as soon as the UI action finishes, then at the same
   roughly 30-second and two-minute idle intervals. Note B in Settings
   and in a fresh tab's sidebar, and run one scan in that tab too. Keep A
   unchanged as the original direct-PATCH comparison throughout.
4. **Unarchive B once through Settings, Archived chats**, while recording
   Network. Repeat the same listing and visibility checks. A UI restore
   result does not demonstrate that a direct unarchive will work. If the
   action times out or its outcome is ambiguous, stop; do not replay it
   or loop archive/unarchive to force agreement.

This experiment contains no scripted mutation. The two deliberate UI
actions affect only the throwaway B. Leave A unchanged until its evidence
has been recorded. If B's restoration remains uncertain, record it for
manual reconciliation; do not assume cleanup succeeded.

## Request comparison

For the UI archive and unarchive, record method, redacted path, status,
body shape, response shape, all additional operations and the **actual
outgoing header names** from Network. Compare the old direct-PATCH capture
if you still have it. If not, mark its wire headers unknown: the current
GET-only check cannot recover historical PATCH headers. No new direct
PATCH is part of this experiment.

Compare account/workspace/device context values **locally**, reporting
only same/different/unknown. Header names alone cannot establish equal
context. Never share authorization, cookie, session, account or device
values, titles, full IDs, raw responses or copied request commands.
Record header names only. The two headers supplied by the original
caller are not necessarily all the headers its fetch wrapper sent.

## Reading the results

| Observation | What it supports; what remains open |
| --- | --- |
| A converges with no further mutation | Lag or caching is plausible. This bounds only these observed windows; it does not prove a general deadline or authoritative source. |
| B converges but A still disagrees | A direct-request/context/UI-effects difference is plausible. Compare complete request sequences and wire headers before choosing one-variable follow-up tests. |
| A and B both disagree | The issue may affect current UI/listing consistency too. Neither listing is validated for mutation verification. |
| Fresh-tab and original-tab reads differ | A tab/cache/context difference deserves isolation. A fresh tab does not itself prove server truth. |
| Both listings agree, sidebar differs | Investigate sidebar projection separately; listing agreement does not establish why sidebar state differs. |
| Restore disagrees or is incomplete | Undo remains unverified even if archive appeared to work. Preserve uncertainty. |
| A listing errors, caps out or has pagination anomalies | Presence can be observed; absence and final state cannot be inferred from that scan. |

Do not infer that a longer wait, extra header or second PATCH fixes the
problem. Select a later experiment from the evidence. Product archive and
undo remain blocked by the [mutation gates](../docs/api-findings.md#mutation-gates)
until a trustworthy preflight/readback rule, intended request context,
direct restore evidence and manifest ownership semantics are established.

## What to return

Paste only the redacted checker reports and a small table of observations:

| Phase / alias | Action and elapsed time | Sidebar now / fresh tab | Settings archived | Request sequence, status, header names | Context same/different/unknown |
| --- | --- | --- | --- | --- | --- |
| A baseline / later | No mutation; note intervening history | | | Historical capture available/unknown | |
| B baseline / archive | UI archive once | | | | |
| B restore | UI unarchive once | | | | |

Include incomplete scans, duplicate rows and unknowns. The results can
then be recorded under questions 8, 11 and 13 in
[api-findings.md](../docs/api-findings.md). Keep the queue entry open while
the disagreement or its verification rule remains unresolved.
