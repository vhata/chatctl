// chatctl discovery probe.
//
// Paste this whole file into the DevTools console of a logged-in
// https://chatgpt.com tab. It is read-only: the single network helper,
// makeGet, only ever issues GET requests without a body.
//
// The report records structure and counts. It never contains titles, full
// conversation IDs or the access token. It is saved as a local JSON download
// and is not sent anywhere.

(() => {
  "use strict";

  // Hypothesised endpoints. Compare them with the Network tab and edit here
  // if the web app uses something different.
  const ENDPOINTS = {
    session: "/api/auth/session",
    conversations: "/backend-api/conversations",
    projects: "/backend-api/gizmos/snorlax/sidebar",
  };

  const FIRST_PAGE_LIMIT = 100;
  const PAGE_DELAY_MS = 500;
  const MAX_PAGES = 200;
  const AGE_THRESHOLDS_DAYS = [30, 60, 90, 180, 365];
  const SAMPLE_SIZE = 3;
  const PROJECT_KEY_RE = /gizmo|project|workspace|snorlax/i;
  const TIME_KEY_RE = /time|_at$/i;
  const DAY_MS = 86_400_000;

  function makeGet(fetchImpl, token) {
    return async function get(path) {
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const response = await fetchImpl(path, { method: "GET", headers });
      let body = null;
      try {
        body = await response.json();
      } catch {
        body = null;
      }
      return { status: response.status, body };
    };
  }

  function typeOf(value) {
    if (value === null || value === undefined) return "null";
    if (Array.isArray(value)) return "array";
    return typeof value;
  }

  // A shape-only description of a value: no string content survives.
  function describe(value) {
    switch (typeOf(value)) {
      case "null":
        return null;
      case "number":
      case "boolean":
        return value;
      case "string":
        return `<string:${value.length}>`;
      case "array":
        return `<array:${value.length}>`;
      case "object":
        return `<object:${Object.keys(value).join(",")}>`;
      default:
        return `<${typeof value}>`;
    }
  }

  // Like describe, but keeps the first 8 characters of strings. Used for IDs
  // and project-membership fields, where a short prefix helps tell values
  // apart without exposing them.
  function truncate(value) {
    return typeof value === "string" ? value.slice(0, 8) : describe(value);
  }

  function timestampFormat(value) {
    if (value === null || value === undefined) return "null";
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return "number:other";
      return value > 1e11 ? "epoch-ms" : "epoch-s";
    }
    if (typeof value === "string") {
      if (/^\d{4}-\d{2}-\d{2}T/.test(value)) return "iso8601";
      if (/^\d+(\.\d+)?$/.test(value)) return "numeric-string";
      return "string:other";
    }
    return typeOf(value);
  }

  function toDate(value) {
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return null;
      return new Date(value > 1e11 ? value : value * 1000);
    }
    if (typeof value === "string") {
      if (/^\d+(\.\d+)?$/.test(value)) return toDate(Number(value));
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? null : date;
    }
    return null;
  }

  function monthKey(date) {
    return date.toISOString().slice(0, 7);
  }

  function bump(counts, key) {
    counts[key] = (counts[key] ?? 0) + 1;
  }

  function sortedDesc(counts) {
    return Object.fromEntries(
      Object.entries(counts).sort(([a], [b]) => b.localeCompare(a)),
    );
  }

  function redactItem(item) {
    const out = {};
    for (const [key, value] of Object.entries(item ?? {})) {
      if (key === "title") {
        out[key] = typeof value === "string" ? `<title:${value.length}>` : describe(value);
      } else if (key === "id" || PROJECT_KEY_RE.test(key)) {
        out[key] = truncate(value);
      } else if (TIME_KEY_RE.test(key)) {
        out[key] = timestampFormat(value);
      } else {
        out[key] = describe(value);
      }
    }
    return out;
  }

  function describeTopLevel(body) {
    if (typeOf(body) !== "object") return describe(body);
    return Object.fromEntries(
      Object.entries(body).map(([key, value]) => [key, describe(value)]),
    );
  }

  function summariseItems(items) {
    const fields = {};
    for (const item of items) {
      for (const [key, value] of Object.entries(item ?? {})) {
        const field = (fields[key] ??= { count: 0, types: {} });
        field.count += 1;
        bump(field.types, typeOf(value));
        if (TIME_KEY_RE.test(key)) {
          field.formats ??= {};
          bump(field.formats, timestampFormat(value));
        }
        if (PROJECT_KEY_RE.test(key)) {
          field.values ??= {};
          bump(field.values, String(truncate(value)));
        }
      }
    }
    return { item_count: items.length, fields };
  }

  function aggregate(items, now) {
    const byUpdateMonth = {};
    const byCreateMonth = {};
    const olderThanDays = Object.fromEntries(AGE_THRESHOLDS_DAYS.map((days) => [days, 0]));
    for (const item of items) {
      const updated = toDate(item?.update_time);
      const created = toDate(item?.create_time);
      bump(byUpdateMonth, updated ? monthKey(updated) : "unknown");
      bump(byCreateMonth, created ? monthKey(created) : "unknown");
      if (!updated) continue;
      const ageDays = (now.getTime() - updated.getTime()) / DAY_MS;
      for (const days of AGE_THRESHOLDS_DAYS) {
        if (ageDays > days) olderThanDays[days] += 1;
      }
    }
    return {
      by_update_month: sortedDesc(byUpdateMonth),
      by_create_month: sortedDesc(byCreateMonth),
      older_than_days: olderThanDays,
    };
  }

  function defaultSleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // Walks a paginated list endpoint. Stops on the first of: a non-200
  // response, a body without an items array, an empty page, a page that adds
  // no unseen IDs (the server ignoring offset), a reported total being
  // reached, or maxPages. onPage(pageNumber, itemsSoFar) is called after each
  // page that adds items.
  async function walkList(get, path, options = {}) {
    const {
      firstLimit = FIRST_PAGE_LIMIT,
      maxPages = MAX_PAGES,
      delayMs = PAGE_DELAY_MS,
      sleep = defaultSleep,
      onPage = () => {},
    } = options;
    const separator = path.includes("?") ? "&" : "?";
    const items = [];
    const seen = new Set();
    const pages = [];
    let offset = 0;
    let limit = firstLimit;
    let effectiveLimit = null;
    let stopReason = "max_pages";

    for (let page = 0; page < maxPages; page += 1) {
      if (page > 0) await sleep(delayMs);
      const { status, body } = await get(
        `${path}${separator}offset=${offset}&limit=${limit}&order=updated`,
      );
      const pageItems = Array.isArray(body?.items) ? body.items : null;
      pages.push({
        offset,
        requested_limit: limit,
        status,
        top_level: describeTopLevel(body),
        item_count: pageItems ? pageItems.length : null,
      });
      if (status !== 200) {
        stopReason = `http_${status}`;
        break;
      }
      if (pageItems === null) {
        stopReason = "no_items_array";
        break;
      }
      if (pageItems.length === 0) {
        stopReason = "empty_page";
        break;
      }
      let fresh = 0;
      for (const item of pageItems) {
        const id = item?.id;
        if (id !== undefined && seen.has(id)) continue;
        if (id !== undefined) seen.add(id);
        items.push(item);
        fresh += 1;
      }
      if (fresh === 0) {
        stopReason = "no_new_items";
        break;
      }
      onPage(page + 1, items.length);
      offset += pageItems.length;
      if (typeof body.total === "number" && offset >= body.total) {
        stopReason = "reached_total";
        break;
      }
      limit = typeof body.limit === "number" && body.limit > 0 ? body.limit : pageItems.length;
      effectiveLimit ??= limit;
    }

    return {
      items,
      pages,
      stop_reason: stopReason,
      requested_first_limit: firstLimit,
      effective_limit: effectiveLimit,
    };
  }

  async function probeList(get, path, now, options = {}) {
    const walk = await walkList(get, path, options);
    return {
      path,
      stop_reason: walk.stop_reason,
      requested_first_limit: walk.requested_first_limit,
      effective_limit: walk.effective_limit,
      pages: walk.pages,
      summary: summariseItems(walk.items),
      samples: walk.items.slice(0, SAMPLE_SIZE).map(redactItem),
      aggregates: aggregate(walk.items, now),
    };
  }

  async function probeSingle(get, path) {
    const { status, body } = await get(path);
    const items = Array.isArray(body?.items) ? body.items : null;
    return {
      path,
      status,
      top_level: describeTopLevel(body),
      summary: items ? summariseItems(items) : null,
      samples: items ? items.slice(0, SAMPLE_SIZE).map(redactItem) : null,
    };
  }

  async function runProbe(fn) {
    try {
      return await fn();
    } catch (error) {
      return { error: String(error) };
    }
  }

  async function buildReport(fetchImpl, now, options = {}) {
    const anonymous = makeGet(fetchImpl, null);
    const session = await anonymous(ENDPOINTS.session);
    const report = {
      tool: "chatctl-probe",
      version: 1,
      generated_at: now.toISOString(),
      endpoints: ENDPOINTS,
      session: { status: session.status, top_level: describeTopLevel(session.body) },
      probes: {},
    };
    const token = session.body?.accessToken;
    if (typeof token !== "string") {
      report.error = "no accessToken in the session response; are you logged in?";
      return report;
    }
    const get = makeGet(fetchImpl, token);
    report.probes.conversations = await runProbe(() =>
      probeList(get, ENDPOINTS.conversations, now, options),
    );
    report.probes.archived = await runProbe(() =>
      probeList(get, `${ENDPOINTS.conversations}?is_archived=true`, now, {
        ...options,
        maxPages: 1,
      }),
    );
    report.probes.projects = await runProbe(() => probeSingle(get, ENDPOINTS.projects));
    return report;
  }

  function reportFilename(report) {
    const stamp = report.generated_at.replace(/:/g, "").replace(/\.\d+Z$/, "Z");
    return `chatctl-probe-${stamp}.json`;
  }

  function download(report) {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = reportFilename(report);
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  function logSummary(report) {
    console.log("chatctl probe finished:", report.error ?? "ok");
    for (const [name, probe] of Object.entries(report.probes)) {
      const count = probe.summary?.item_count ?? "n/a";
      const stop = probe.stop_reason ?? probe.status ?? probe.error;
      console.log(`  ${name}: ${count} items (${stop})`);
    }
    console.log(`Report saved as ${reportFilename(report)}`);
  }

  async function main() {
    console.log("chatctl probe running (read-only)...");
    const onPage = (page, count) => console.log(`  page ${page}: ${count} conversations so far`);
    const report = await buildReport(window.fetch.bind(window), new Date(), { onPage });
    download(report);
    logSummary(report);
  }

  if (typeof window === "undefined") {
    module.exports = {
      ENDPOINTS,
      makeGet,
      describe,
      truncate,
      timestampFormat,
      toDate,
      redactItem,
      summariseItems,
      aggregate,
      walkList,
      buildReport,
      reportFilename,
    };
  } else {
    main().catch((error) => console.error("chatctl probe failed:", error));
  }
})();
