// USER-RUN diagnostic: paste this file in https://chatgpt.com DevTools,
// then await chatctlListingCheck(). Pasting only defines the function.
// Prompts and credentials stay in memory. Only GETs are made; the returned
// report contains aliases and field classifications, never account values.
(() => {
  "use strict";

  const LIMIT = 100;
  const MAX_PAGES = 200;
  const DELAY_MS = 500;
  const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const owns = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

  async function runListingCheck({
    origin,
    targets,
    fetchImpl,
    sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now = Date.now,
    timeoutMs = 15000,
  }) {
    const aliases = targets && targets.B ? ["A", "B"] : ["A"];
    const freshListing = () => ({
      started: null,
      finished: null,
      pages: 0,
      complete: false,
      stop: "not_started",
      targets: Object.fromEntries(aliases.map((alias) => [alias, { presence: "unknown", observations: [] }])),
    });
    const report = {
      version: 1,
      stop: null,
      listings: { default: freshListing(), archived: freshListing() },
      updateTimeEquality: Object.fromEntries(aliases.map((alias) => [alias, "unknown"])),
    };
    if (origin !== "https://chatgpt.com") {
      report.stop = "invalid_origin";
      return report;
    }
    if (!object(targets) || typeof targets.A !== "string" || !targets.A.trim() ||
        (targets.B !== undefined && (typeof targets.B !== "string" || !targets.B.trim())) ||
        targets.A === targets.B) {
      report.stop = "invalid_targets";
      return report;
    }

    // All requests, including session and list switches, share this clock.
    let previousStart = null;
    let token = null;
    async function get(path) {
      if (previousStart !== null) {
        const remaining = DELAY_MS - (now() - previousStart);
        if (remaining > 0) await sleep(remaining);
      }
      previousStart = now();
      const controller = new AbortController();
      let timer;
      const timeout = new Promise((resolve) => {
        timer = setTimeout(() => {
          controller.abort();
          resolve({ stop: "timeout" });
        }, timeoutMs);
      });
      try {
        return await Promise.race([
          (async () => {
            try {
              const response = await fetchImpl(path, {
                method: "GET",
                cache: "no-store",
                headers: token ? { Authorization: `Bearer ${token}` } : {},
                signal: controller.signal,
              });
              if (!response || !Number.isInteger(response.status) || response.status < 100 || response.status > 599) {
                return { stop: "invalid_response" };
              }
              if (response.status !== 200) return { stop: "http_error", status: response.status };
              try {
                return { body: await response.json() };
              } catch {
                return { stop: "invalid_json" };
              }
            } catch {
              return { stop: "request_error" };
            }
          })(),
          timeout,
        ]);
      } finally {
        clearTimeout(timer);
      }
    }

    const session = await get("/api/auth/session");
    if (session.stop || !object(session.body) || typeof session.body.accessToken !== "string" || !session.body.accessToken.trim()) {
      report.stop = session.stop || "invalid_session";
      if (session.status) report.status = session.status;
      return report;
    }
    token = session.body.accessToken;
    const times = Object.fromEntries(aliases.map((alias) => [alias, { default: [], archived: [] }]));
    for (const name of ["default", "archived"]) {
      const listing = report.listings[name];
      listing.started = new Date(now()).toISOString();
      const seen = new Set();
      let offset = 0;
      for (let page = 0; page < MAX_PAGES; page += 1) {
        const path = `/backend-api/conversations?offset=${offset}&limit=${LIMIT}&order=updated${name === "archived" ? "&is_archived=true" : ""}`;
        const result = await get(path);
        if (result.stop) {
          listing.stop = result.stop;
          if (result.status) listing.status = result.status;
          break;
        }
        const body = result.body;
        if (!object(body) || !Array.isArray(body.items) || body.items.length > LIMIT ||
            body.limit !== LIMIT || body.offset !== offset ||
            !Number.isSafeInteger(body.total) || body.total < offset + body.items.length ||
            (body.items.length === 0 && body.total !== offset)) {
          listing.stop = "invalid_page";
          break;
        }
        if (body.items.some((item) => !object(item) || typeof item.id !== "string" || !item.id)) {
          listing.stop = "invalid_item";
          break;
        }
        listing.pages += 1;
        let duplicate = false;
        for (const item of body.items) {
          if (seen.has(item.id)) duplicate = true;
          seen.add(item.id);
          for (const alias of aliases) {
            if (item.id !== targets[alias]) continue;
            const target = listing.targets[alias];
            target.presence = "present";
            target.observations.push({
              page: listing.pages,
              is_archived: !owns(item, "is_archived") ? "missing" : typeof item.is_archived === "boolean" ? item.is_archived : "invalid",
              gizmo_id: !owns(item, "gizmo_id") ? "missing" : item.gizmo_id === null ? "null" : "set",
            });
            times[alias][name].push(typeof item.update_time === "string" &&
              /^\d{4}-\d{2}-\d{2}T.*Z$/.test(item.update_time) && Number.isFinite(Date.parse(item.update_time)) ? item.update_time : null);
          }
        }
        if (duplicate) {
          listing.stop = "duplicate_id";
          break;
        }
        if (body.items.length === 0 || offset + body.items.length >= body.total) {
          listing.complete = true;
          listing.stop = "complete";
          break;
        }
        offset += body.items.length;
        listing.stop = "page_cap";
      }
      listing.finished = new Date(now()).toISOString();
      for (const alias of aliases) {
        const target = listing.targets[alias];
        if (listing.complete && target.presence !== "present") target.presence = "absent";
      }
      // Stop the experiment after any non-clean scan. No retries or further
      // requests after rate limits, server errors, or uncertain pagination.
      if (!listing.complete) {
        report.stop = listing.stop;
        break;
      }
    }
    for (const alias of aliases) {
      const values = times[alias];
      if (values.default.length && values.archived.length &&
          !values.default.includes(null) && !values.archived.includes(null)) {
        report.updateTimeEquality[alias] = values.default.every((left) => values.archived.every((right) => left === right)) ? "equal" : "different";
      }
    }
    if (!report.stop) report.stop = "complete";
    token = null;
    return report;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { runListingCheck };
  } else if (typeof window !== "undefined") {
    // Preserve the page's current wrapped fetch; never replace or bypass it.
    const pageFetch = window.fetch.bind(window);
    window.chatctlListingCheck = async () => {
      if (window.location.origin !== "https://chatgpt.com") {
        return runListingCheck({ origin: window.location.origin });
      }
      const A = window.prompt("Local ID for alias A (original direct PATCH); Cancel stops.");
      if (!A || !A.trim()) return { version: 1, stop: "cancelled" };
      const B = window.prompt("Optional local ID for alias B (UI control); blank or Cancel skips B.");
      return runListingCheck({
        origin: window.location.origin,
        targets: { A: A.trim(), ...(B && B.trim() ? { B: B.trim() } : {}) },
        fetchImpl: pageFetch,
      });
    };
  }
})();
