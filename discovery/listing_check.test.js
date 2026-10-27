"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const { runListingCheck } = require("./listing_check.js");

const SECRET = "private-token-title-id-never-print";
const TARGET = `target-${SECRET}`;
const STAMP = "2026-10-01T00:00:00Z";
const row = (id, fields = {}) => ({ id, title: SECRET, gizmo_id: null, is_archived: false, update_time: STAMP, ...fields });
const page = (offset, items, total = offset + items.length) => ({ offset, limit: 100, items, total });

function fixture(handler, options = {}) {
  let clock = Date.parse("2026-10-26T00:00:00Z");
  const calls = [];
  const sleeps = [];
  let active = 0;
  let maxActive = 0;
  const fetchImpl = async (path, init) => {
    calls.push({ path, init, time: clock });
    active += 1;
    maxActive = Math.max(maxActive, active);
    try {
      if (path === "/api/auth/session") return { status: 200, json: async () => ({ accessToken: SECRET }) };
      const url = new URL(path, "https://chatgpt.test");
      const result = await handler({ archived: url.searchParams.get("is_archived") === "true", offset: Number(url.searchParams.get("offset")) });
      return { status: 200, json: async () => result };
    } finally {
      active -= 1;
    }
  };
  const run = (overrides = {}) => runListingCheck({
    origin: "https://chatgpt.com",
    targets: { A: TARGET },
    fetchImpl,
    sleep: async (ms) => { sleeps.push(ms); clock += ms; },
    now: () => clock,
    ...options,
    ...overrides,
  });
  return { run, calls, sleeps, maxActive: () => maxActive };
}

function redacted(report) {
  const text = JSON.stringify(report);
  assert.ok(!text.includes(SECRET), text);
  assert.ok(!text.includes(TARGET), text);
  assert.ok(!text.includes(STAMP), text);
}

test("completes both listings past first archived page and reports target absence only after full scan", async () => {
  const f = fixture(({ archived, offset }) => {
    if (!archived) return page(0, []);
    if (!offset) return page(0, Array.from({ length: 100 }, (_, i) => row(`other-${i}`)), 101);
    return page(100, [row(TARGET, { is_archived: true })]);
  });
  const result = await f.run({ targets: { A: TARGET, B: "missing-control" } });
  assert.equal(result.stop, "complete");
  assert.equal(result.listings.archived.pages, 2);
  assert.equal(result.listings.default.targets.A.presence, "absent");
  assert.equal(result.listings.archived.targets.A.presence, "present");
  assert.equal(result.listings.archived.targets.B.presence, "absent");
  assert.deepEqual(result.listings.archived.targets.A.observations, [{ page: 2, is_archived: true, gizmo_id: "null" }]);
  assert.equal(result.updateTimeEquality.A, "unknown");
  assert.equal(f.calls.length, 4);
  assert.equal(f.maxActive(), 1);
  for (let i = 0; i < f.calls.length; i += 1) {
    assert.equal(f.calls[i].init.method, "GET");
    assert.equal(f.calls[i].init.cache, "no-store");
    assert.equal(f.calls[i].init.body, undefined);
    assert.equal(f.calls[i].init.headers.Authorization, i ? `Bearer ${SECRET}` : undefined);
    if (i) assert.ok(f.calls[i].time - f.calls[i - 1].time >= 500);
  }
  assert.deepEqual(f.sleeps, [500, 500, 500]);
  assert.ok(result.listings.default.started < result.listings.default.finished);
  assert.ok(result.listings.archived.started <= result.listings.archived.finished);
  redacted(result);
});

test("preserves contradictory observations across lists and compares only update-time equality", async () => {
  const f = fixture(({ archived }) => page(0, [row(TARGET, { is_archived: !archived, gizmo_id: archived ? SECRET : null })]));
  const result = await f.run();
  assert.equal(result.listings.default.targets.A.observations[0].is_archived, true);
  assert.equal(result.listings.archived.targets.A.observations[0].is_archived, false);
  assert.equal(result.listings.archived.targets.A.observations[0].gizmo_id, "set");
  assert.equal(result.updateTimeEquality.A, "equal");
  redacted(result);
  const different = fixture(({ archived }) => page(0, [row(TARGET, { update_time: archived ? "2026-10-02T00:00:00Z" : STAMP })]));
  assert.equal((await different.run()).updateTimeEquality.A, "different");
});

test("missing and invalid metadata are classifications, with unknown update-time comparison", async () => {
  const f = fixture(({ archived }) => page(0, [archived ? { id: TARGET, is_archived: SECRET, gizmo_id: SECRET } : { id: TARGET }]));
  const result = await f.run();
  assert.deepEqual(result.listings.default.targets.A.observations, [{ page: 1, is_archived: "missing", gizmo_id: "missing" }]);
  assert.deepEqual(result.listings.archived.targets.A.observations, [{ page: 1, is_archived: "invalid", gizmo_id: "set" }]);
  assert.equal(result.updateTimeEquality.A, "unknown");
  redacted(result);
});

test("invalid origin and duplicate target IDs never fetch", async () => {
  const f = fixture(() => assert.fail("must not list"));
  for (const origin of ["http://chatgpt.com", "https://chatgpt.com.evil.test", "https://chatgpt.com:443", SECRET]) {
    const result = await f.run({ origin });
    assert.equal(result.stop, "invalid_origin");
    redacted(result);
  }
  assert.equal((await f.run({ targets: { A: TARGET, B: TARGET } })).stop, "invalid_targets");
  assert.equal(f.calls.length, 0);
});

test("invalid session shapes stop before listing and never print session content", async () => {
  for (const body of [null, [], { accessToken: 42, user: SECRET }, { accessToken: " " }]) {
    let count = 0;
    const f = fixture(() => assert.fail("must not list"));
    const result = await f.run({ fetchImpl: async () => { count += 1; return { status: 200, json: async () => body }; } });
    assert.equal(result.stop, "invalid_session");
    assert.equal(count, 1);
    redacted(result);
  }
});

test("invalid listing shapes/offset/limit/total/items leave absence unknown and halt", async () => {
  const invalid = [null, [], {}, page(1, []), { ...page(0, []), limit: 20 },
    page(0, [], -1), page(0, [], 1.5), page(0, [row(TARGET)], 0),
    page(0, Array.from({ length: 101 }, (_, i) => row(`row-${i}`))),
    page(0, [{ title: SECRET }]), page(0, [null])];
  for (const body of invalid) {
    const f = fixture(() => body);
    const result = await f.run();
    assert.ok(["invalid_page", "invalid_item"].includes(result.stop));
    assert.equal(result.listings.default.complete, false);
    assert.equal(result.listings.default.targets.A.presence, "unknown");
    assert.equal(result.listings.archived.stop, "not_started");
    assert.equal(f.calls.length, 2);
    redacted(result);
  }
});

test("repeated pages and within-page duplicates halt, preserving contradictory target rows", async () => {
  const f = fixture(({ offset }) => page(offset, [row(TARGET, { is_archived: offset > 0 })], offset + 2));
  const result = await f.run();
  assert.equal(result.stop, "duplicate_id");
  assert.equal(result.listings.default.pages, 2);
  assert.equal(result.listings.default.complete, false);
  assert.deepEqual(result.listings.default.targets.A.observations.map((o) => o.is_archived), [false, true]);
  const within = fixture(() => page(0, [row(TARGET), row(TARGET, { is_archived: true })]));
  assert.equal((await within.run()).stop, "duplicate_id");
  redacted(result);
});

test("200-page cap bounds listings and cannot imply absence", async () => {
  const f = fixture(({ offset }) => page(offset, [row(`row-${offset}`)], offset + 2));
  const result = await f.run();
  assert.equal(result.stop, "page_cap");
  assert.equal(result.listings.default.pages, 200);
  assert.equal(result.listings.default.targets.A.presence, "unknown");
  assert.equal(f.calls.length, 201);
});

test("HTTP errors stop without reading response bodies, retries, or leaking response text", async () => {
  for (const status of [401, 403, 429, 500, 503]) {
    const f = fixture(() => assert.fail("unused"));
    let count = 0;
    const result = await f.run({ fetchImpl: async () => {
      count += 1;
      if (count === 1) return { status: 200, json: async () => ({ accessToken: SECRET }) };
      return { status, statusText: SECRET, json: async () => assert.fail("must not read body") };
    } });
    assert.equal(result.stop, "http_error");
    assert.equal(result.listings.default.status, status);
    assert.equal(result.listings.default.targets.A.presence, "unknown");
    assert.equal(count, 2);
    redacted(result);
  }
});

test("request errors, malformed JSON, and invalid responses are fixed redacted categories", async () => {
  for (const [fetchImpl, stop] of [
    [async () => { throw new Error(SECRET); }, "request_error"],
    [async () => ({ status: 200, json: async () => { throw new Error(SECRET); } }), "invalid_json"],
    [async () => ({ status: SECRET }), "invalid_response"],
  ]) {
    const f = fixture(() => assert.fail("unused"));
    const result = await f.run({ fetchImpl });
    assert.equal(result.stop, stop);
    redacted(result);
  }
});

test("timeout bounds both fetch and JSON parsing and aborts without leaking exception content", async () => {
  for (const parsing of [false, true]) {
    let signal;
    const f = fixture(() => assert.fail("unused"));
    const result = await f.run({ timeoutMs: 5, fetchImpl: async (_path, init) => {
      signal = init.signal;
      const hang = new Promise(() => {});
      return parsing ? { status: 200, json: () => hang } : hang;
    } });
    assert.equal(result.stop, "timeout");
    assert.equal(signal.aborted, true);
    redacted(result);
  }
});

test("browser paste defines callable without fetching, preserves wrapped fetch, and prompts each run", async () => {
  const calls = [];
  const prompts = [];
  const window = {
    location: { origin: "https://chatgpt.com" },
    prompt: (message) => { prompts.push(message); return prompts.length % 2 ? TARGET : null; },
    fetch: async function (path, init) {
      assert.equal(this, window);
      calls.push({ path, init });
      return { status: 200, json: async () => path === "/api/auth/session" ? { accessToken: SECRET } : page(0, []) };
    },
  };
  const source = fs.readFileSync(require.resolve("./listing_check.js"), "utf8");
  let tick = Date.now();
  class FakeDate extends Date { static now() { tick += 500; return tick; } }
  vm.runInNewContext(source, { window, AbortController, setTimeout, clearTimeout, Date: FakeDate });
  assert.equal(calls.length, 0);
  assert.equal(typeof window.chatctlListingCheck, "function");
  window.fetch = () => assert.fail("must preserve original wrapper");
  redacted(await window.chatctlListingCheck());
  redacted(await window.chatctlListingCheck());
  assert.equal(prompts.length, 4);
  assert.equal(calls.length, 6);
});
