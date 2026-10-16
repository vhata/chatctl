"""Read-only proof of concept for the browser transport.

Pages the full conversation listing by evaluating JavaScript in a logged-in
chatgpt.com tab through remaldi (`remaldi evaluate`), with Python driving the
loop: one page per evaluation, one evaluation at a time, a pause between
pages, and bounded retries with backoff on 429, 5xx and timeouts.

Each evaluation fetches /api/auth/session, then one page of
/backend-api/conversations, and returns only shape data and aggregate counts:
never titles, IDs, the token or any other item content. The access token
stays inside the page. Every request the page makes goes through one helper
that only issues GET.

Run it with `uv run python discovery/transport_poc.py`; see
discovery/README.md. It prints a summary to stdout, progress to stderr, and
writes no files. Standard library only.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

PAGE_LIMIT = 100
PAGE_DELAY_SECONDS = 0.5
MAX_PAGES = 200
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = (2.0, 4.0, 8.0)
MAX_RETRY_AFTER_SECONDS = 60.0
# remaldi gives each DevTools request five seconds and reports a slower one as
# unknown_outcome. The page aborts its own requests first, so a slow request is
# never left running in the tab while the next one starts.
PAGE_TIMEOUT_MS = 4000
# remaldi's own limits: eight seconds to start its service, twelve per
# operation. This only catches a hung process.
RUNNER_TIMEOUT_SECONDS = 30.0
CHATGPT_ORIGIN = "https://chatgpt.com"
DEFAULT_DEVTOOLS_ENDPOINT = "http://127.0.0.1:9222"

# The aggregate counts the page script returns, in the order they are printed.
# update_time and create_time count timestamp shapes: z, offset or no_offset,
# each with "+fraction" when there are fractional seconds, or null, missing,
# not_string or string_not_iso8601.
COUNT_GROUPS = ("gizmo_id", "is_archived", "update_time", "create_time", "title", "id")

# remaldi error codes after which the same GET may be sent again: the request
# timed out or its response was lost.
RETRYABLE_REMALDI_CODES = frozenset({"unknown_outcome"})

PAGE_SCRIPT = """(async () => {
  "use strict";
  const OFFSET = __OFFSET__;
  const LIMIT = __LIMIT__;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), __TIMEOUT_MS__);
  const transportFailure = () => ({
    transport: controller.signal.aborted ? "timeout" : "network",
  });

  // The only network helper: GET without a body, nothing else.
  async function get(path, token) {
    const headers = token === null ? {} : { Authorization: `Bearer ${token}` };
    try {
      return await fetch(path, { method: "GET", headers, signal: controller.signal });
    } catch {
      throw transportFailure();
    }
  }

  async function readJson(response) {
    try {
      return { parsed: await response.json() };
    } catch {
      if (controller.signal.aborted) throw transportFailure();
      return null;
    }
  }

  function retryAfter(response) {
    const raw = response.headers.get("retry-after");
    const seconds = raw === null || raw.trim() === "" ? NaN : Number(raw);
    return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
  }

  function httpFailure(stage, response) {
    return {
      ok: false,
      stage,
      status: response.status,
      retry_after: retryAfter(response),
      error: "http",
    };
  }

  const isObject = (value) =>
    value !== null && typeof value === "object" && !Array.isArray(value);
  const number = (value) =>
    typeof value === "number" && Number.isFinite(value) ? value : null;
  const bump = (counts, key) => {
    counts[key] = (counts[key] ?? 0) + 1;
  };

  function gizmoKind(item) {
    if (!Object.hasOwn(item, "gizmo_id")) return "missing";
    const value = item.gizmo_id;
    if (value === null) return "null";
    if (typeof value !== "string") return "other_type";
    return value.startsWith("g-p-") ? "project_prefix" : "other_string";
  }

  function archivedKind(item) {
    if (!Object.hasOwn(item, "is_archived")) return "missing";
    const value = item.is_archived;
    if (value === true || value === false || value === null) return String(value);
    return "other_type";
  }

  // The shape of a timestamp, never its value: whether it is ISO 8601, ends
  // in Z, carries a numeric UTC offset or none, and has fractional seconds.
  function timeShape(item, key) {
    if (!Object.hasOwn(item, key)) return "missing";
    const value = item[key];
    if (value === null) return "null";
    if (typeof value !== "string") return "not_string";
    const iso = /^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}(?::\\d{2}(\\.\\d+)?)?(Z|[+-]\\d{2}:?\\d{2})?$/;
    const match = iso.exec(value);
    if (match === null) return "string_not_iso8601";
    const zone = match[2] === undefined ? "no_offset" : match[2] === "Z" ? "z" : "offset";
    return match[1] === undefined ? zone : `${zone}+fraction`;
  }

  function titleKind(item) {
    if (!Object.hasOwn(item, "title")) return "missing";
    if (item.title === null) return "null";
    return typeof item.title === "string" ? "string" : "other_type";
  }

  function idKind(item) {
    if (!Object.hasOwn(item, "id")) return "missing";
    return typeof item.id === "string" && item.id !== "" ? "string" : "other";
  }

  function shape(body) {
    const keys = Object.keys(body);
    const listable = keys.length <= 20 && keys.every((key) => /^[a-z_][a-z0-9_]{0,39}$/.test(key));
    const items = Array.isArray(body.items) ? body.items : null;
    const counts = {
      gizmo_id: {},
      is_archived: {},
      update_time: {},
      create_time: {},
      title: {},
      id: {},
    };
    for (const item of items ?? []) {
      if (!isObject(item)) {
        bump(counts.id, "not_an_object");
        continue;
      }
      bump(counts.gizmo_id, gizmoKind(item));
      bump(counts.is_archived, archivedKind(item));
      bump(counts.update_time, timeShape(item, "update_time"));
      bump(counts.create_time, timeShape(item, "create_time"));
      bump(counts.title, titleKind(item));
      bump(counts.id, idKind(item));
    }
    return {
      keys: listable ? keys.sort() : null,
      keys_count: keys.length,
      total: number(body.total),
      offset: number(body.offset),
      limit: number(body.limit),
      items_length: items === null ? null : items.length,
      counts,
    };
  }

  let stage = "origin";
  try {
    if (location.origin !== "__ORIGIN__") return { ok: false, stage, error: "wrong_origin" };
    stage = "session";
    const session = await get("/api/auth/session", null);
    if (session.status !== 200) return httpFailure(stage, session);
    let token = null;
    const sessionJson = await readJson(session);
    const accessToken = sessionJson?.parsed?.accessToken;
    if (typeof accessToken === "string" && accessToken !== "") token = accessToken;
    if (token === null) return { ok: false, stage, status: 200, error: "no_token" };
    stage = "list";
    const response = await get(
      `/backend-api/conversations?offset=${OFFSET}&limit=${LIMIT}&order=updated`,
      token,
    );
    token = null;
    if (response.status !== 200) return httpFailure(stage, response);
    const listJson = await readJson(response);
    if (listJson === null || !isObject(listJson.parsed)) {
      return { ok: false, stage, status: 200, error: "not_a_json_object" };
    }
    return {
      ok: true,
      session_status: session.status,
      status: response.status,
      ...shape(listJson.parsed),
    };
  } catch (error) {
    if (isObject(error) && typeof error.transport === "string") {
      return { ok: false, stage, error: error.transport };
    }
    const safeName = typeof error?.name === "string" && /^[A-Za-z]{1,40}$/.test(error.name);
    return { ok: false, stage, error: "exception", name: safeName ? error.name : "Error" };
  } finally {
    clearTimeout(timer);
  }
})()"""


def build_page_expression(
    offset: int, limit: int = PAGE_LIMIT, timeout_ms: int = PAGE_TIMEOUT_MS
) -> str:
    """The JavaScript evaluated in the tab for one page of the listing."""
    for name, value in (
        ("offset", offset),
        ("limit", limit),
        ("timeout_ms", timeout_ms),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    return (
        PAGE_SCRIPT.replace("__OFFSET__", str(offset))
        .replace("__LIMIT__", str(limit))
        .replace("__TIMEOUT_MS__", str(timeout_ms))
        .replace("__ORIGIN__", CHATGPT_ORIGIN)
    )


def remaldi_command(remaldi: str, target: str, expression: str) -> list[str]:
    return [
        remaldi,
        "evaluate",
        "--target",
        target,
        "--await-promise",
        "--return-by-value",
        "--",
        expression,
    ]


@dataclass(frozen=True)
class Page:
    """Shape data for one page, as returned by the page script."""

    offset: int
    status: int
    keys: tuple[str, ...] | None
    keys_count: int
    total: int | None
    response_offset: int | None
    limit: int | None
    items: int
    counts: dict[str, dict[str, int]]


@dataclass(frozen=True)
class Failure:
    """Why an attempt at a page failed, and whether the GET may be repeated."""

    kind: str
    detail: str
    retryable: bool
    status: int | None = None
    retry_after: float | None = None


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _counts(value: object) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    if not isinstance(value, dict):
        return out
    for group, buckets in value.items():
        if not isinstance(group, str) or not isinstance(buckets, dict):
            continue
        out[group] = {
            str(key): count
            for key, raw in buckets.items()
            if (count := _int(raw)) is not None
        }
    return out


def _is_retryable_status(status: int | None) -> bool:
    return status is not None and (status == 429 or 500 <= status <= 599)


def _remaldi_error(stderr: str) -> tuple[str, str]:
    try:
        error = json.loads(stderr)["error"]
        return str(error["code"]), str(error.get("message", ""))
    except (ValueError, KeyError, TypeError):
        lines = stderr.strip().splitlines()
        return "unparsed", lines[-1][:200] if lines else ""


def parse_page_value(offset: int, value: object) -> Page | Failure:
    """Interpret the page script's return value."""
    if not isinstance(value, dict):
        return Failure("unexpected_value", "the page script returned no object", False)
    status = _int(value.get("status"))
    if value.get("ok") is not True:
        error = str(value.get("error", "unknown"))
        stage = str(value.get("stage", "unknown"))
        if error == "http":
            raw_retry_after = value.get("retry_after")
            retry_after = (
                float(raw_retry_after)
                if isinstance(raw_retry_after, int | float)
                and not isinstance(raw_retry_after, bool)
                else None
            )
            return Failure(
                f"http_{status}",
                f"{stage} request returned HTTP {status}",
                _is_retryable_status(status),
                status=status,
                retry_after=retry_after,
            )
        if error in {"timeout", "network"}:
            return Failure(error, f"{stage} request: {error}", True)
        if error == "exception":
            return Failure(
                "exception", f"{stage}: {value.get('name', 'Error')} thrown", False
            )
        return Failure(error, f"{stage}: {error}", False, status=status)
    items = _int(value.get("items_length"))
    if status != 200 or items is None:
        return Failure(
            "unexpected_shape", "the listing response has no items array", False
        )
    raw_keys = value.get("keys")
    keys = (
        tuple(str(key) for key in raw_keys)
        if isinstance(raw_keys, list) and all(isinstance(key, str) for key in raw_keys)
        else None
    )
    return Page(
        offset=offset,
        status=status,
        keys=keys,
        keys_count=_int(value.get("keys_count")) or 0,
        total=_int(value.get("total")),
        response_offset=_int(value.get("offset")),
        limit=_int(value.get("limit")),
        items=items,
        counts=_counts(value.get("counts")),
    )


def parse_remaldi_output(
    offset: int, returncode: int, stdout: str, stderr: str
) -> Page | Failure:
    """Interpret one `remaldi evaluate` run.

    remaldi exits 1 with `{"error": {"code", "message", ...}}` on stderr when
    the call itself fails. Otherwise it exits 0 and prints the DevTools
    Runtime.evaluate result on stdout: `{"result": {"type", "value"}}`, plus
    `exceptionDetails` when the JavaScript threw, which still exits 0.
    """
    if returncode != 0:
        code, message = _remaldi_error(stderr)
        detail = f"remaldi exited {returncode}: {code}" + (
            f" ({message})" if message else ""
        )
        return Failure(f"remaldi_{code}", detail, code in RETRYABLE_REMALDI_CODES)
    try:
        output = json.loads(stdout)
    except ValueError:
        return Failure(
            "remaldi_output", "remaldi printed something other than JSON", False
        )
    if not isinstance(output, dict):
        return Failure(
            "remaldi_output", "remaldi printed something other than an object", False
        )
    if "exceptionDetails" in output:
        # The exception's description could quote anything the page held, so
        # only its class name is reported.
        details = output.get("exceptionDetails")
        exception = details.get("exception") if isinstance(details, dict) else None
        name = exception.get("className") if isinstance(exception, dict) else None
        label = name if isinstance(name, str) and name.isidentifier() else "unknown"
        return Failure(
            "javascript_exception", f"the page script threw ({label})", False
        )
    result = output.get("result")
    if not isinstance(result, dict) or "value" not in result:
        return Failure(
            "remaldi_output", "remaldi returned no value; was the target a page?", False
        )
    return parse_page_value(offset, result["value"])


def retry_delay(failure: Failure, retry: int) -> float:
    """Seconds to wait before retry number `retry` (1-based)."""
    delay = BACKOFF_SECONDS[min(retry, len(BACKOFF_SECONDS)) - 1]
    if failure.retry_after is not None:
        delay = max(delay, min(failure.retry_after, MAX_RETRY_AFTER_SECONDS))
    return delay


def should_stop(page: Page) -> str | None:
    """The stop rule from docs/api-findings.md, question 2.

    Page until a page is empty or `offset + len(items) >= total`. The first
    page's total is not the size of the history.
    """
    if page.items == 0:
        return "empty_page"
    if page.total is None:
        return "no_total"
    if page.offset + page.items >= page.total:
        return "reached_total"
    return None


def total_pattern(page: Page) -> str:
    """How a page's total compares with question 2's description.

    "more": total is offset + limit + 1 (at least one more item).
    "final": total is offset + len(items) (the real count).
    """
    if page.total is None:
        return "missing"
    if page.total == page.offset + page.items:
        return "final"
    limit = page.limit if page.limit is not None else PAGE_LIMIT
    if page.total == page.offset + limit + 1:
        return "more"
    return "other"


def matches_question_2(pages: Sequence[Page], stop_reason: str) -> bool:
    """Whether the run behaved as question 2 says: full pages reporting
    offset + limit + 1, then a final page reporting the real count."""
    if not pages or stop_reason not in {"reached_total", "empty_page"}:
        return False
    *middle, last = pages
    for page in middle:
        limit = page.limit if page.limit is not None else PAGE_LIMIT
        if total_pattern(page) != "more" or page.items != limit:
            return False
    return total_pattern(last) == "final"


@dataclass
class Walk:
    pages: list[Page] = field(default_factory=list)
    page_seconds: list[float] = field(default_factory=list)
    retries: dict[str, int] = field(default_factory=dict)
    stop_reason: str = "not_started"
    failure: Failure | None = None
    requests: int = 0
    elapsed: float = 0.0


class RunResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str]], RunResult]


def walk_listing(
    run: Runner,
    remaldi: str,
    target: str,
    *,
    max_pages: int = MAX_PAGES,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    progress: Callable[[str], None] = lambda _line: None,
) -> Walk:
    """Page the listing one evaluation at a time until the stop rule fires,
    a page fails for good, or max_pages pages have been fetched."""
    walk = Walk(stop_reason="max_pages")
    started = clock()
    offset = 0
    for number in range(1, max_pages + 1):
        if number > 1:
            sleep(PAGE_DELAY_SECONDS)
        outcome: Page | Failure | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if attempt > 1:
                assert isinstance(outcome, Failure)
                delay = retry_delay(outcome, attempt - 1)
                progress(
                    f"  retrying offset {offset} in {delay:g} s after {outcome.detail}"
                )
                sleep(delay)
            command = remaldi_command(remaldi, target, build_page_expression(offset))
            call_started = clock()
            try:
                result = run(command)
                outcome = parse_remaldi_output(
                    offset, result.returncode, result.stdout, result.stderr
                )
            except subprocess.TimeoutExpired:
                outcome = Failure(
                    "runner_timeout", "remaldi did not finish in time", True
                )
            call_seconds = clock() - call_started
            walk.requests += 1
            if isinstance(outcome, Page) or not outcome.retryable:
                break
            walk.retries[outcome.kind] = walk.retries.get(outcome.kind, 0) + 1
        assert outcome is not None
        if isinstance(outcome, Failure):
            walk.failure = outcome
            walk.stop_reason = "failed"
            break
        walk.pages.append(outcome)
        walk.page_seconds.append(call_seconds)
        progress(
            f"page {number}: offset {outcome.offset}, {outcome.items} items, "
            f"total {outcome.total} ({total_pattern(outcome)}), {call_seconds:.2f} s"
        )
        reason = should_stop(outcome)
        if reason is not None:
            walk.stop_reason = reason
            break
        offset += outcome.items
    walk.elapsed = clock() - started
    return walk


def aggregate_counts(pages: Sequence[Page]) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    for page in pages:
        for group, buckets in page.counts.items():
            target = totals.setdefault(group, {})
            for key, count in buckets.items():
                target[key] = target.get(key, 0) + count
    return totals


def _format_buckets(buckets: dict[str, int]) -> str:
    if not buckets:
        return "none"
    return ", ".join(f"{key} {count}" for key, count in sorted(buckets.items()))


def format_summary(walk: Walk, target: str) -> list[str]:
    """The lines printed at the end. Aggregate counts and shape only."""
    pages = walk.pages
    items = sum(page.items for page in pages)
    last_total = pages[-1].total if pages else None
    patterns: dict[str, int] = {}
    for page in pages:
        patterns[total_pattern(page)] = patterns.get(total_pattern(page), 0) + 1
    echoed = sum(1 for page in pages if page.response_offset == page.offset)
    key_sets = sorted(
        {
            ",".join(page.keys) if page.keys else f"<{page.keys_count} keys>"
            for page in pages
        }
    )
    lines = [
        "chatctl transport proof of concept (read-only)",
        f"target: {target}",
        f"stop: {walk.stop_reason} after {len(pages)} pages",
        f"items: {items}; last reported total: {last_total}",
        "question 2 pattern: "
        + ("matched" if matches_question_2(pages, walk.stop_reason) else "not matched")
        + f" (page totals: {_format_buckets(patterns)})",
        f"offset echoed: {echoed} of {len(pages)} pages",
        f"top-level keys: {'; '.join(key_sets) if key_sets else 'none'}",
    ]
    counts = aggregate_counts(pages)
    for group in COUNT_GROUPS:
        lines.append(f"{group}: {_format_buckets(counts.get(group, {}))}")
    lines.append(f"retries: {_format_buckets(walk.retries)}")
    lines.append(
        f"evaluations: {walk.requests} (each makes one session GET and at most one listing GET)"
    )
    if walk.page_seconds:
        average = sum(walk.page_seconds) / len(walk.page_seconds)
        lines.append(
            f"elapsed: {walk.elapsed:.1f} s; per page average {average:.2f} s, "
            f"max {max(walk.page_seconds):.2f} s"
        )
    else:
        lines.append(f"elapsed: {walk.elapsed:.1f} s")
    if walk.failure is not None:
        lines.append(f"error: {walk.failure.kind}: {walk.failure.detail}")
    else:
        lines.append("error: none")
    return lines


def chatgpt_page_targets(targets: object) -> list[str]:
    """IDs of DevTools page targets showing chatgpt.com, from /json/list."""
    if not isinstance(targets, list):
        return []
    found = []
    for target in targets:
        if not isinstance(target, dict) or target.get("type") != "page":
            continue
        url = target.get("url")
        identifier = target.get("id")
        if (
            isinstance(url, str)
            and isinstance(identifier, str)
            and (url == CHATGPT_ORIGIN or url.startswith(CHATGPT_ORIGIN + "/"))
        ):
            found.append(identifier)
    return found


def devtools_endpoint() -> str:
    """The debugger endpoint remaldi uses: REMALDI_ENDPOINT or port 9222."""
    endpoint = os.environ.get("REMALDI_ENDPOINT", DEFAULT_DEVTOOLS_ENDPOINT).rstrip("/")
    url = urllib.parse.urlsplit(endpoint)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("REMALDI_ENDPOINT must be a loopback HTTP URL")
    return endpoint


def list_devtools_targets(endpoint: str) -> object:
    """Read the browser's local target list, as remaldi does. Loopback only."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(endpoint + "/json/list", timeout=2) as response:
        return json.load(response)


def run_remaldi(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=RUNNER_TIMEOUT_SECONDS,
        check=False,
    )


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only: page the ChatGPT conversation listing through remaldi "
            "and print shape data and aggregate counts."
        )
    )
    parser.add_argument(
        "--target",
        help=(
            "DevTools target ID of the logged-in chatgpt.com tab. Default: the "
            "only chatgpt.com page in the browser's /json/list."
        ),
    )
    parser.add_argument("--remaldi", default="remaldi", help="remaldi executable")
    parser.add_argument(
        "--max-pages",
        type=_positive_int,
        default=MAX_PAGES,
        help=f"stop after this many pages (default {MAX_PAGES})",
    )
    return parser.parse_args(argv)


def resolve_target(explicit: str | None) -> str:
    if explicit:
        return explicit
    endpoint = devtools_endpoint()
    try:
        found = chatgpt_page_targets(list_devtools_targets(endpoint))
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"error: could not read {endpoint}/json/list ({exc.__class__.__name__}). "
            "Is Vivaldi running with --remote-debugging-port=9222?"
        ) from exc
    if len(found) != 1:
        raise SystemExit(
            f"error: found {len(found)} chatgpt.com tabs; open exactly one, "
            "or pass --target with its ID"
        )
    return found[0]


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    target = resolve_target(args.target)
    print(
        f"paging the listing through remaldi, target {target} (read-only)",
        file=sys.stderr,
    )
    walk = walk_listing(
        run_remaldi,
        args.remaldi,
        target,
        max_pages=args.max_pages,
        progress=lambda line: print(line, file=sys.stderr, flush=True),
    )
    print("\n".join(format_summary(walk, target)))
    return 0 if walk.stop_reason in {"reached_total", "empty_page"} else 1


if __name__ == "__main__":
    sys.exit(main())
