// Tests for the pure parts of probe.js. Run with: node --test discovery/
"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");

const probe = require("./probe.js");

const NOW = new Date("2026-10-08T12:00:00Z");
const noSleep = async () => {};

function fakeFetch(handler) {
  const calls = [];
  const fetchImpl = async (path, init) => {
    calls.push({ path, init });
    const { status = 200, body } = handler(path);
    return {
      status,
      json: async () => {
        if (body === undefined) throw new SyntaxError("not json");
        return body;
      },
    };
  };
  return { fetchImpl, calls };
}

function getFor(handler) {
  return probe.makeGet(fakeFetch(handler).fetchImpl, "token");
}

function pageParams(path) {
  const url = new URL(path, "https://chatgpt.test");
  return {
    offset: Number(url.searchParams.get("offset")),
    limit: Number(url.searchParams.get("limit")),
  };
}

function conversations(count) {
  return Array.from({ length: count }, (_, index) => ({
    id: `conversation-${String(index).padStart(4, "0")}-full-identifier`,
    title: `Title number ${index}`,
    update_time: "2026-09-01T00:00:00Z",
  }));
}

test("makeGet sends only GET with no body and a bearer token", async () => {
  const { fetchImpl, calls } = fakeFetch(() => ({ body: { ok: true } }));
  const result = await probe.makeGet(fetchImpl, "secret-token")("/x");
  assert.deepEqual(result, { status: 200, body: { ok: true } });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.body, undefined);
  assert.equal(calls[0].init.headers.Authorization, "Bearer secret-token");
});

test("makeGet without a token sends no Authorization header", async () => {
  const { fetchImpl, calls } = fakeFetch(() => ({ body: {} }));
  await probe.makeGet(fetchImpl, null)("/x");
  assert.deepEqual(calls[0].init.headers, {});
});

test("makeGet returns a null body for non-JSON responses", async () => {
  const { fetchImpl } = fakeFetch(() => ({ status: 502, body: undefined }));
  assert.deepEqual(await probe.makeGet(fetchImpl, null)("/x"), { status: 502, body: null });
});

test("describe keeps shape and drops string content", () => {
  assert.equal(probe.describe("hello"), "<string:5>");
  assert.equal(probe.describe([1, 2, 3]), "<array:3>");
  assert.equal(probe.describe({ a: 1, b: "x" }), "<object:a,b>");
  assert.equal(probe.describe(42), 42);
  assert.equal(probe.describe(false), false);
  assert.equal(probe.describe(null), null);
  assert.equal(probe.describe(undefined), null);
});

test("truncate keeps eight characters of strings only", () => {
  assert.equal(probe.truncate("g-p-1234567890"), "g-p-1234");
  assert.equal(probe.truncate({ id: "x" }), "<object:id>");
  assert.equal(probe.truncate(null), null);
});

test("timestampFormat recognises the common encodings", () => {
  assert.equal(probe.timestampFormat("2026-10-08T12:00:00.000000Z"), "iso8601");
  assert.equal(probe.timestampFormat(1759924800), "epoch-s");
  assert.equal(probe.timestampFormat(1759924800.123), "epoch-s");
  assert.equal(probe.timestampFormat(1759924800123), "epoch-ms");
  assert.equal(probe.timestampFormat("1759924800.5"), "numeric-string");
  assert.equal(probe.timestampFormat("yesterday"), "string:other");
  assert.equal(probe.timestampFormat(null), "null");
  assert.equal(probe.timestampFormat(Number.NaN), "number:other");
});

test("toDate handles ISO strings, epoch seconds and milliseconds", () => {
  const expected = Date.parse("2025-10-08T12:00:00Z");
  assert.equal(probe.toDate("2025-10-08T12:00:00Z").getTime(), expected);
  assert.equal(probe.toDate(expected / 1000).getTime(), expected);
  assert.equal(probe.toDate(expected).getTime(), expected);
  assert.equal(probe.toDate(String(expected / 1000)).getTime(), expected);
  assert.equal(probe.toDate("not a date"), null);
  assert.equal(probe.toDate(null), null);
  assert.equal(probe.toDate(undefined), null);
});

test("aggregate buckets by month and counts ages by update_time", () => {
  const items = [
    { update_time: "2026-10-01T00:00:00Z", create_time: "2024-01-05T00:00:00Z" },
    { update_time: Date.parse("2026-06-15T00:00:00Z") / 1000, create_time: null },
    { update_time: "2025-01-01T00:00:00Z", create_time: "2025-01-01T00:00:00Z" },
    { update_time: null },
  ];
  const result = probe.aggregate(items, NOW);
  assert.deepEqual(result.by_update_month, {
    unknown: 1,
    "2026-10": 1,
    "2026-06": 1,
    "2025-01": 1,
  });
  assert.deepEqual(result.by_create_month, { unknown: 2, "2025-01": 1, "2024-01": 1 });
  assert.deepEqual(result.older_than_days, { 30: 2, 60: 2, 90: 2, 180: 1, 365: 1 });
});

test("redactItem never keeps titles, full IDs or other string content", () => {
  const redacted = probe.redactItem({
    id: "0123456789abcdef-full-id",
    title: "Secret plans for Tuesday",
    update_time: 1759924800,
    snippet: "private words",
    gizmo_id: "g-p-abcdef123456",
    is_archived: false,
    mapping: { a: 1 },
  });
  assert.deepEqual(redacted, {
    id: "01234567",
    title: "<title:24>",
    update_time: "epoch-s",
    snippet: "<string:13>",
    gizmo_id: "g-p-abcd",
    is_archived: false,
    mapping: "<object:a>",
  });
});

test("summariseItems records types, timestamp formats and project values", () => {
  const summary = probe.summariseItems([
    { id: "a", update_time: "2026-01-01T00:00:00Z", gizmo_id: null },
    { id: "b", update_time: 1759924800, gizmo_id: "g-p-abcdef123456" },
    { id: "c", update_time: 1759924800 },
  ]);
  assert.equal(summary.item_count, 3);
  assert.deepEqual(summary.fields.id, { count: 3, types: { string: 3 } });
  assert.deepEqual(summary.fields.update_time.formats, { iso8601: 1, "epoch-s": 2 });
  assert.deepEqual(summary.fields.gizmo_id.values, { null: 1, "g-p-abcd": 1 });
  assert.equal(summary.fields.gizmo_id.count, 2);
});

test("walkList follows the page size the server reports", async () => {
  const all = conversations(70);
  const seenLimits = [];
  const get = getFor((path) => {
    const { offset, limit } = pageParams(path);
    seenLimits.push(limit);
    return { body: { items: all.slice(offset, offset + Math.min(limit, 28)), limit: 28 } };
  });
  const walk = await probe.walkList(get, "/list", { sleep: noSleep });
  assert.equal(walk.items.length, 70);
  assert.equal(walk.stop_reason, "empty_page");
  assert.equal(walk.requested_first_limit, 100);
  assert.equal(walk.effective_limit, 28);
  assert.deepEqual(seenLimits, [100, 28, 28, 28]);
});

test("walkList does not stop early on a short page without a total", async () => {
  const all = conversations(50);
  const get = getFor((path) => {
    const { offset } = pageParams(path);
    return { body: { items: all.slice(offset, offset + 20) } };
  });
  const walk = await probe.walkList(get, "/list", { sleep: noSleep });
  assert.equal(walk.items.length, 50);
  assert.equal(walk.stop_reason, "empty_page");
  assert.equal(walk.effective_limit, 20);
});

test("walkList stops when the reported total is reached", async () => {
  const all = conversations(30);
  const get = getFor((path) => {
    const { offset, limit } = pageParams(path);
    return { body: { items: all.slice(offset, offset + limit), total: 30, limit } };
  });
  const walk = await probe.walkList(get, "/list", { firstLimit: 10, sleep: noSleep });
  assert.equal(walk.items.length, 30);
  assert.equal(walk.stop_reason, "reached_total");
  assert.equal(walk.pages.length, 3);
});

test("walkList stops when the server ignores offset", async () => {
  const first = conversations(5);
  const get = getFor(() => ({ body: { items: first } }));
  const walk = await probe.walkList(get, "/list", { sleep: noSleep });
  assert.equal(walk.items.length, 5);
  assert.equal(walk.stop_reason, "no_new_items");
  assert.equal(walk.pages.length, 2);
});

test("walkList stops at maxPages", async () => {
  let next = 0;
  const get = getFor(() => ({ body: { items: [{ id: `id-${next++}` }] } }));
  const walk = await probe.walkList(get, "/list", { maxPages: 4, sleep: noSleep });
  assert.equal(walk.pages.length, 4);
  assert.equal(walk.stop_reason, "max_pages");
});

test("walkList records HTTP errors and missing item arrays", async () => {
  const limited = await probe.walkList(getFor(() => ({ status: 429, body: {} })), "/list", {
    sleep: noSleep,
  });
  assert.equal(limited.stop_reason, "http_429");
  assert.equal(limited.items.length, 0);
  const odd = await probe.walkList(getFor(() => ({ body: { data: [] } })), "/list", {
    sleep: noSleep,
  });
  assert.equal(odd.stop_reason, "no_items_array");
});

test("walkList sleeps between pages and reports progress", async () => {
  const all = conversations(3);
  let sleeps = 0;
  const progress = [];
  const get = getFor((path) => {
    const { offset } = pageParams(path);
    return { body: { items: all.slice(offset, offset + 1) } };
  });
  await probe.walkList(get, "/list", {
    sleep: async () => {
      sleeps += 1;
    },
    onPage: (page, count) => progress.push([page, count]),
  });
  assert.equal(sleeps, 3);
  assert.deepEqual(progress, [
    [1, 1],
    [2, 2],
    [3, 3],
  ]);
});

test("walkList appends paging parameters to paths that already have a query", async () => {
  const { fetchImpl, calls } = fakeFetch(() => ({ body: { items: [] } }));
  await probe.walkList(probe.makeGet(fetchImpl, "t"), "/list?is_archived=true", {
    sleep: noSleep,
  });
  assert.equal(calls[0].path, "/list?is_archived=true&offset=0&limit=100&order=updated");
});

test("buildReport never contains titles, full IDs or the token", async () => {
  const all = conversations(4);
  const { fetchImpl, calls } = fakeFetch((path) => {
    if (path === probe.ENDPOINTS.session) {
      return { body: { accessToken: "very-secret-token-value", user: { email: "a@b.c" } } };
    }
    if (path.startsWith(probe.ENDPOINTS.projects)) {
      return { body: { items: [{ gizmo: { id: "g-p-123", name: "Home server" } }] } };
    }
    const { offset } = pageParams(path);
    return { body: { items: all.slice(offset, offset + 2) } };
  });
  const report = await probe.buildReport(fetchImpl, NOW, { sleep: noSleep });
  const text = JSON.stringify(report);
  assert.ok(!text.includes("very-secret-token-value"));
  assert.ok(!text.includes("a@b.c"));
  assert.ok(!text.includes("Home server"));
  for (const conversation of all) {
    assert.ok(!text.includes(conversation.title));
    assert.ok(!text.includes(conversation.id));
  }
  assert.equal(report.probes.conversations.summary.item_count, 4);
  assert.ok(calls.every((call) => call.init.method === "GET" && call.init.body === undefined));
});

test("buildReport stops after the session call when there is no token", async () => {
  const { fetchImpl, calls } = fakeFetch(() => ({ body: {} }));
  const report = await probe.buildReport(fetchImpl, NOW, { sleep: noSleep });
  assert.match(report.error, /no accessToken/);
  assert.equal(calls.length, 1);
  assert.deepEqual(report.probes, {});
});

test("reportFilename uses a filesystem-safe UTC timestamp", () => {
  assert.equal(
    probe.reportFilename({ generated_at: "2026-10-08T17:20:00.123Z" }),
    "chatctl-probe-2026-10-08T172000Z.json",
  );
});

test("redactItem keeps prefixes only for ID-named project fields", () => {
  const redacted = probe.redactItem({
    project_name: "Taxes",
    gizmo_title: "Home server",
    gizmo_type: "snorlax",
    gizmo_id: "g-p-abcdef123456",
    workspaceId: "ws-1234567890",
  });
  assert.deepEqual(redacted, {
    project_name: "<string:5>",
    gizmo_title: "<string:11>",
    gizmo_type: "<string:7>",
    gizmo_id: "g-p-abcd",
    workspaceId: "ws-12345",
  });
  const summary = probe.summariseItems([{ project_name: "Taxes" }]);
  assert.deepEqual(summary.fields.project_name.values, { "<string:5>": 1 });
});

test("describe hides the keys of map-like objects", () => {
  const uuid = "11111111-2222-3333-4444-555555555555";
  assert.equal(probe.describe({ [uuid]: {} }), "<object:1 keys>");
  const wide = Object.fromEntries(Array.from({ length: 31 }, (_, i) => [`k${i}`, i]));
  assert.equal(probe.describe(wide), "<object:31 keys>");
  assert.equal(probe.describe({ a: 1, b: "x" }), "<object:a,b>");
});

test("walkList keeps collected items when a request throws", async () => {
  const all = conversations(5);
  let calls = 0;
  const get = async () => {
    calls += 1;
    if (calls === 1) return { status: 200, body: { items: all.slice(0, 3) } };
    throw new TypeError("Failed to fetch https://chatgpt.test/secret-path");
  };
  const walk = await probe.walkList(get, "/list", { sleep: noSleep });
  assert.equal(walk.items.length, 3);
  assert.equal(walk.stop_reason, "fetch_error");
  assert.equal(walk.pages.at(-1).error, "TypeError");
  assert.ok(!JSON.stringify(walk.pages).includes("secret-path"));
});

test("toDate rejects numbers outside the Date range", () => {
  assert.equal(probe.toDate(1e20), null);
  assert.equal(probe.toDate("100000000000000000000"), null);
  assert.deepEqual(probe.aggregate([{ update_time: 1e20 }], NOW).by_update_month, {
    unknown: 1,
  });
});

test("summariseItems counts boolean values", () => {
  const summary = probe.summariseItems([
    { is_archived: false },
    { is_archived: true },
    { is_archived: false },
    { is_archived: null },
  ]);
  assert.deepEqual(summary.fields.is_archived.booleans, { false: 2, true: 1 });
  assert.equal(summary.fields.is_archived.count, 4);
});

test("summariseItems summarises nested objects one level down", () => {
  const summary = probe.summariseItems([
    {
      gizmo: {
        id: "g-p-abcdef123456",
        display: { name: "Home server" },
        gizmo_type: "snorlax",
        archived: false,
      },
    },
    { gizmo: { id: "g-p-zzzzzzzzzzzz", archived: true } },
  ]);
  const nested = summary.fields.gizmo.fields;
  assert.deepEqual(nested.id, { count: 2, types: { string: 2 } });
  assert.deepEqual(nested.display.types, { object: 1 });
  assert.equal(nested.display.fields, undefined);
  assert.deepEqual(nested.gizmo_type.values, { "<string:7>": 1 });
  assert.deepEqual(nested.archived.booleans, { false: 1, true: 1 });
  const text = JSON.stringify(summary);
  assert.ok(!text.includes("Home server"));
  assert.ok(!text.includes("abcdef123456"));
});

test("summariseItems does not descend into ID-keyed maps", () => {
  const uuid = "11111111-2222-3333-4444-555555555555";
  const summary = probe.summariseItems([{ mapping: { [uuid]: { parent: null } } }]);
  assert.equal(summary.fields.mapping.fields, undefined);
  assert.ok(!JSON.stringify(summary).includes(uuid));
});

test("walkList records the page size when the first page reaches total", async () => {
  const get = getFor(() => ({ body: { items: conversations(2), total: 2, limit: 28 } }));
  const walk = await probe.walkList(get, "/list", { sleep: noSleep });
  assert.equal(walk.stop_reason, "reached_total");
  assert.equal(walk.effective_limit, 28);
});
