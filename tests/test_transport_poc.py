"""Tests for discovery/transport_poc.py, behind a fake remaldi runner.

Nothing here reaches a browser or chatgpt.com. The page script itself is run
under Node with a fake fetch when Node is available.
"""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

_PATH = Path(__file__).resolve().parents[1] / "discovery" / "transport_poc.py"
_SPEC = importlib.util.spec_from_file_location("transport_poc", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
poc = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = poc
_SPEC.loader.exec_module(poc)

TOKEN = "SECRET-TOKEN-must-not-leave-the-page"
TARGET = "TARGET-ID"


def page_value(
    offset: int, items: int | None, total: int | None, **extra: object
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "ok": True,
        "session_status": 200,
        "status": 200,
        "keys": ["items", "limit", "offset", "total"],
        "keys_count": 4,
        "total": total,
        "offset": offset,
        "limit": 100,
        "items_length": items,
        "counts": {
            "gizmo_id": {"null": items},
            "gizmo_and_template": {"neither": items},
            "is_archived": {"false": items},
            "update_time": {"z+fraction": items},
            "create_time": {"z+fraction": items},
            "title": {"string": items},
            "id": {"string": items},
        },
    }
    value.update(extra)
    return value


def evaluated(value: object) -> str:
    return json.dumps({"result": {"type": "object", "value": value}})


def completed(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def offset_of(command: Sequence[str]) -> int:
    match = re.search(r"const OFFSET = (\d+);", command[-1])
    assert match is not None
    return int(match.group(1))


Response = subprocess.CompletedProcess[str] | BaseException


class FakeRemaldi:
    """Stands in for the remaldi subprocess. `script` maps a requested offset
    to a list of responses, consumed one per call."""

    def __init__(self, script: Mapping[int, Sequence[Response]]) -> None:
        self.script = {offset: list(responses) for offset, responses in script.items()}
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        response = self.script[offset_of(command)].pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        self.now += 0.25
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def walk(fake: FakeRemaldi, **kwargs: Any) -> tuple[Any, FakeClock]:
    clock = FakeClock()
    result = poc.walk_listing(
        fake, "remaldi", TARGET, sleep=clock.sleep, clock=clock, **kwargs
    )
    return result, clock


# The page expression and the remaldi command


def test_expression_embeds_offset_limit_and_origin():
    expression = poc.build_page_expression(300)
    assert "const OFFSET = 300;" in expression
    assert "const LIMIT = 100;" in expression
    assert '"https://chatgpt.com"' in expression
    assert "__" not in re.sub(r"__remaldi", "", expression)


def test_expression_issues_get_only_through_one_helper():
    expression = poc.build_page_expression(0)
    assert expression.count("fetch(") == 1
    assert 'method: "GET"' in expression
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        assert method not in expression
    assert "body:" not in expression


@pytest.mark.parametrize("offset", [-1, True, 1.5, "0"])
def test_expression_rejects_bad_offsets(offset):
    with pytest.raises(ValueError):
        poc.build_page_expression(offset)


def test_remaldi_command_awaits_and_returns_by_value():
    command = poc.remaldi_command("remaldi", TARGET, "(expr)")
    assert command == [
        "remaldi",
        "evaluate",
        "--target",
        TARGET,
        "--await-promise",
        "--return-by-value",
        "--",
        "(expr)",
    ]


# Parsing remaldi's output


def test_parses_a_successful_page():
    page = poc.parse_remaldi_output(100, 0, evaluated(page_value(100, 100, 201)), "")
    assert page == poc.Page(
        offset=100,
        status=200,
        keys=("items", "limit", "offset", "total"),
        keys_count=4,
        total=201,
        response_offset=100,
        limit=100,
        items=100,
        counts={
            "gizmo_id": {"null": 100},
            "gizmo_and_template": {"neither": 100},
            "is_archived": {"false": 100},
            "update_time": {"z+fraction": 100},
            "create_time": {"z+fraction": 100},
            "title": {"string": 100},
            "id": {"string": 100},
        },
    )


def test_remaldi_unknown_outcome_is_retryable():
    stderr = json.dumps(
        {"error": {"code": "unknown_outcome", "message": "not replayed"}}
    )
    failure = poc.parse_remaldi_output(0, 1, "", stderr)
    assert failure.kind == "remaldi_unknown_outcome"
    assert failure.retryable


@pytest.mark.parametrize(
    "code",
    ["target_unavailable", "endpoint_unavailable", "devtools_error", "startup_failed"],
)
def test_other_remaldi_errors_are_fatal(code):
    stderr = json.dumps({"error": {"code": code, "message": "m"}})
    failure = poc.parse_remaldi_output(0, 1, "", stderr)
    assert failure.kind == f"remaldi_{code}"
    assert not failure.retryable


def test_unparseable_remaldi_error_is_fatal():
    failure = poc.parse_remaldi_output(0, 2, "", "usage: remaldi ...\nerror: bad\n")
    assert failure.kind == "remaldi_unparsed"
    assert not failure.retryable


def test_javascript_exception_reports_only_the_class_name():
    output = json.dumps(
        {
            "result": {"type": "object", "subtype": "error"},
            "exceptionDetails": {
                "text": "Uncaught",
                "exception": {
                    "className": "TypeError",
                    "description": f"TypeError: {TOKEN}",
                },
            },
        }
    )
    failure = poc.parse_remaldi_output(0, 0, output, "")
    assert failure.kind == "javascript_exception"
    assert "TypeError" in failure.detail
    assert TOKEN not in failure.detail
    assert not failure.retryable


@pytest.mark.parametrize(
    "stdout", ["not json", "[]", json.dumps({"result": {"type": "undefined"}})]
)
def test_unexpected_remaldi_output_is_fatal(stdout):
    failure = poc.parse_remaldi_output(0, 0, stdout, "")
    assert isinstance(failure, poc.Failure)
    assert not failure.retryable


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(429, True), (500, True), (503, True), (401, False), (404, False)],
)
def test_http_failures_retry_only_on_429_and_5xx(status, retryable):
    value = {
        "ok": False,
        "stage": "list",
        "status": status,
        "error": "http",
        "retry_after": None,
    }
    failure = poc.parse_page_value(0, value)
    assert failure.kind == f"http_{status}"
    assert failure.retryable is retryable


def test_retry_after_is_kept():
    value = {
        "ok": False,
        "stage": "list",
        "status": 429,
        "error": "http",
        "retry_after": 7,
    }
    assert poc.parse_page_value(0, value).retry_after == 7.0


@pytest.mark.parametrize(("error", "retryable"), [("timeout", True), ("network", True)])
def test_transport_failures_in_the_page_are_retryable(error, retryable):
    failure = poc.parse_page_value(0, {"ok": False, "stage": "session", "error": error})
    assert failure.retryable is retryable


@pytest.mark.parametrize(
    "error", ["no_token", "wrong_origin", "not_a_json_object", "exception"]
)
def test_other_page_failures_are_fatal(error):
    failure = poc.parse_page_value(0, {"ok": False, "stage": "list", "error": error})
    assert not failure.retryable


def test_a_listing_without_items_is_fatal():
    failure = poc.parse_page_value(0, page_value(0, None, 1))
    assert failure.kind == "unexpected_shape"


# Stop rule and question 2


def make_page(offset: int, items: int, total: int | None, limit: int = 100) -> Any:
    return poc.Page(offset, 200, None, 4, total, offset, limit, items, {})


@pytest.mark.parametrize(
    ("page", "reason"),
    [
        (make_page(0, 100, 101), None),
        (make_page(100, 100, 201), None),
        (make_page(200, 34, 234), "reached_total"),
        (make_page(200, 100, 300), "reached_total"),
        (make_page(300, 0, 300), "empty_page"),
        (make_page(0, 5, None), "no_total"),
    ],
)
def test_stop_rule(page, reason):
    assert poc.should_stop(page) == reason


@pytest.mark.parametrize(
    ("page", "pattern"),
    [
        (make_page(0, 100, 101), "more"),
        (make_page(200, 34, 234), "final"),
        (make_page(0, 100, 5000), "other"),
        (make_page(0, 100, None), "missing"),
    ],
)
def test_total_pattern(page, pattern):
    assert poc.total_pattern(page) == pattern


def test_question_2_pattern_matches():
    pages = [make_page(0, 100, 101), make_page(100, 100, 201), make_page(200, 34, 234)]
    assert poc.matches_question_2(pages, "reached_total")


def test_question_2_pattern_matches_a_single_short_page():
    assert poc.matches_question_2([make_page(0, 34, 34)], "reached_total")


def test_question_2_pattern_rejects_a_true_total_on_the_first_page():
    pages = [make_page(0, 100, 234), make_page(100, 100, 234), make_page(200, 34, 234)]
    assert not poc.matches_question_2(pages, "reached_total")


def test_question_2_pattern_needs_a_clean_stop():
    assert not poc.matches_question_2([make_page(0, 100, 101)], "failed")


def test_retry_delay_backs_off_and_honours_retry_after():
    plain = poc.Failure("http_503", "", True)
    assert [poc.retry_delay(plain, n) for n in (1, 2, 3, 4)] == [2.0, 4.0, 8.0, 8.0]
    assert poc.retry_delay(poc.Failure("http_429", "", True, retry_after=30), 1) == 30.0
    assert (
        poc.retry_delay(poc.Failure("http_429", "", True, retry_after=900), 1) == 60.0
    )
    assert poc.retry_delay(poc.Failure("http_429", "", True, retry_after=0), 2) == 4.0


# Walking the listing


def test_walks_every_page_one_at_a_time_and_stops_at_the_real_total():
    fake = FakeRemaldi(
        {
            0: [completed(evaluated(page_value(0, 100, 101)))],
            100: [completed(evaluated(page_value(100, 100, 201)))],
            200: [completed(evaluated(page_value(200, 34, 234)))],
        }
    )
    result, clock = walk(fake)
    assert [offset_of(command) for command in fake.commands] == [0, 100, 200]
    assert all(
        command[:3] == ["remaldi", "evaluate", "--target"] for command in fake.commands
    )
    assert result.stop_reason == "reached_total"
    assert result.failure is None
    assert result.requests == 3
    assert clock.sleeps == [poc.PAGE_DELAY_SECONDS, poc.PAGE_DELAY_SECONDS]
    assert poc.matches_question_2(result.pages, result.stop_reason)
    assert poc.aggregate_counts(result.pages)["gizmo_id"] == {"null": 234}


def test_an_empty_first_page_stops_cleanly():
    fake = FakeRemaldi({0: [completed(evaluated(page_value(0, 0, 0)))]})
    result, _ = walk(fake)
    assert result.stop_reason == "empty_page"
    assert result.requests == 1


def test_retries_a_429_with_backoff_then_continues():
    limited = {
        "ok": False,
        "stage": "list",
        "status": 429,
        "error": "http",
        "retry_after": 5,
    }
    fake = FakeRemaldi(
        {
            0: [
                completed(evaluated(limited)),
                completed(evaluated(page_value(0, 3, 3))),
            ],
        }
    )
    result, clock = walk(fake)
    assert result.stop_reason == "reached_total"
    assert result.retries == {"http_429": 1}
    assert result.requests == 2
    assert clock.sleeps == [5.0]


def test_gives_up_after_bounded_retries():
    unavailable = {"ok": False, "stage": "list", "status": 503, "error": "http"}
    fake = FakeRemaldi({0: [completed(evaluated(unavailable))] * poc.MAX_ATTEMPTS})
    result, clock = walk(fake)
    assert result.stop_reason == "failed"
    assert result.failure.kind == "http_503"
    assert result.requests == poc.MAX_ATTEMPTS
    assert result.retries == {"http_503": poc.MAX_ATTEMPTS - 1}
    assert clock.sleeps == list(poc.BACKOFF_SECONDS)


def test_stops_without_retrying_on_other_statuses():
    unauthorised = {"ok": False, "stage": "list", "status": 401, "error": "http"}
    fake = FakeRemaldi(
        {
            0: [completed(evaluated(page_value(0, 100, 101)))],
            100: [completed(evaluated(unauthorised))],
        }
    )
    result, _ = walk(fake)
    assert result.stop_reason == "failed"
    assert result.failure.kind == "http_401"
    assert result.requests == 2
    assert len(result.pages) == 1


def test_a_hung_remaldi_is_retried():
    fake = FakeRemaldi(
        {
            0: [
                subprocess.TimeoutExpired("remaldi", 30),
                completed(evaluated(page_value(0, 1, 1))),
            ]
        }
    )
    result, clock = walk(fake)
    assert result.stop_reason == "reached_total"
    assert result.retries == {"runner_timeout": 1}
    assert clock.sleeps == [poc.UNKNOWN_OUTCOME_GRACE_SECONDS]


def test_an_unknown_outcome_waits_out_the_page_timeout_before_retrying():
    unknown = poc.Failure("remaldi_unknown_outcome", "", True)
    grace = poc.PAGE_TIMEOUT_MS / 1000 + 1
    assert poc.retry_delay(unknown, 1) == grace
    assert poc.retry_delay(unknown, 3) == max(grace, poc.BACKOFF_SECONDS[2])


def test_a_missing_remaldi_stops_the_walk():
    fake = FakeRemaldi({0: [FileNotFoundError("remaldi")]})
    result, _ = walk(fake)
    assert result.stop_reason == "failed"
    assert result.failure.kind == "runner_error"
    assert result.requests == 1


def test_stops_when_the_server_ignores_the_offset():
    fake = FakeRemaldi(
        {
            0: [completed(evaluated(page_value(0, 100, 101)))],
            100: [completed(evaluated(page_value(0, 100, 101)))],
        }
    )
    result, _ = walk(fake)
    assert result.stop_reason == "failed"
    assert result.failure.kind == "offset_mismatch"
    assert "requested offset 100, response offset 0" in result.failure.detail
    assert result.requests == 2
    assert len(result.pages) == 1
    text = "\n".join(poc.format_summary(result, TARGET))
    assert "error: offset_mismatch" in text


def test_a_missing_response_offset_is_not_a_mismatch():
    value = page_value(0, 3, 3)
    value["offset"] = None
    fake = FakeRemaldi({0: [completed(evaluated(value))]})
    result, _ = walk(fake)
    assert result.stop_reason == "reached_total"


def test_stops_at_max_pages():
    fake = FakeRemaldi(
        {
            0: [completed(evaluated(page_value(0, 100, 101)))],
            100: [completed(evaluated(page_value(100, 100, 201)))],
        }
    )
    result, _ = walk(fake, max_pages=2)
    assert result.stop_reason == "max_pages"
    assert len(result.pages) == 2


def test_summary_reports_shape_and_counts_only():
    fake = FakeRemaldi(
        {
            0: [completed(evaluated(page_value(0, 100, 101)))],
            100: [completed(evaluated(page_value(100, 7, 107)))],
        }
    )
    result, _ = walk(fake)
    text = "\n".join(poc.format_summary(result, TARGET))
    assert "stop: reached_total after 2 pages" in text
    assert "items: 107; last reported total: 107" in text
    assert "question 2 pattern: matched" in text
    assert "offset echoed: 2 of 2 pages" in text
    assert "top-level keys: items,limit,offset,total" in text
    assert "gizmo_id: null 107" in text
    assert "gizmo_and_template: neither 107" in text
    assert "update_time: z+fraction 107" in text
    assert "create_time: z+fraction 107" in text
    assert "title: string 107" in text
    assert "error: none" in text


def test_summary_names_the_failure():
    fake = FakeRemaldi(
        {0: [completed(stderr=json.dumps({"error": {"code": "x"}}), returncode=1)]}
    )
    result, _ = walk(fake)
    text = "\n".join(poc.format_summary(result, TARGET))
    assert "error: remaldi_x" in text
    assert "question 2 pattern: not matched" in text


# Target discovery


def test_finds_chatgpt_page_targets_only():
    targets = [
        {"id": "A", "type": "page", "url": "https://chatgpt.com/c/abc"},
        {"id": "B", "type": "page", "url": "https://chatgpt.com.evil.example/"},
        {"id": "C", "type": "service_worker", "url": "https://chatgpt.com/sw.js"},
        {"id": "D", "type": "page", "url": "chrome-extension://x/main.html"},
        {"id": "E", "type": "page", "url": "https://chatgpt.com"},
        "junk",
    ]
    assert poc.chatgpt_page_targets(targets) == ["A", "E"]
    assert poc.chatgpt_page_targets({"not": "a list"}) == []


@pytest.mark.parametrize(
    "endpoint", ["http://example.com:9222", "https://127.0.0.1:9222", "file:///tmp"]
)
def test_devtools_endpoint_must_be_loopback(monkeypatch, endpoint):
    monkeypatch.setenv("REMALDI_ENDPOINT", endpoint)
    with pytest.raises(ValueError):
        poc.devtools_endpoint()


def test_devtools_endpoint_defaults_to_port_9222(monkeypatch):
    monkeypatch.delenv("REMALDI_ENDPOINT", raising=False)
    assert poc.devtools_endpoint() == "http://127.0.0.1:9222"


# The page script, run under Node with a fake fetch

NODE_HARNESS = r"""
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const calls = [];
globalThis.location = { origin: input.origin };
globalThis.fetch = (path, init = {}) => {
  calls.push({ path, method: init.method, headers: Object.keys(init.headers ?? {}),
               auth: (init.headers ?? {}).Authorization ?? null, body: init.body ?? null });
  const route = input.routes.find((r) => path.startsWith(r.prefix));
  if (!route || route.hang) {
    return new Promise((resolve, reject) => {
      init.signal?.addEventListener("abort", () => {
        const error = new Error("aborted"); error.name = "AbortError"; reject(error);
      });
    });
  }
  if (route.reject) return Promise.reject(new TypeError("Failed to fetch"));
  return Promise.resolve(new Response(JSON.stringify(route.body),
                                      { status: route.status, headers: route.headers ?? {} }));
};
(0, eval)(input.expression).then((value) => {
  process.stdout.write(JSON.stringify({ value, calls }));
});
"""


def run_page_script(
    routes: list[dict[str, Any]],
    origin: str = "https://chatgpt.com",
    offset: int = 0,
    timeout_ms: int = 4000,
) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    payload = {
        "expression": poc.build_page_expression(offset, timeout_ms=timeout_ms),
        "origin": origin,
        "routes": routes,
    }
    result = subprocess.run(
        [node, "-e", NODE_HARNESS],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout)


SESSION = {
    "prefix": "/api/auth/session",
    "status": 200,
    "body": {
        "accessToken": TOKEN,
        "sessionToken": "SESSION-SECRET",
        "user": {"name": "N"},
    },
}


def listing(
    items: list[dict[str, Any]],
    total: int,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "prefix": "/backend-api/conversations",
        "status": status,
        "headers": headers or {},
        "body": {"items": items, "total": total, "limit": 100, "offset": 0},
    }


ITEMS: list[dict[str, Any]] = [
    {
        "id": "conv-1",
        "title": "TITLE-ONE",
        "gizmo_id": None,
        "is_archived": False,
        "update_time": "2026-01-01T00:00:00Z",
        "create_time": "2025-12-01T10:00:00.123456+00:00",
    },
    {
        "id": "conv-2",
        "title": None,
        "gizmo_id": "g-p-abc",
        "is_archived": False,
        "conversation_template_id": "g-p-abc",
        "update_time": "2026-01-02T00:00:00.5Z",
        "create_time": "2025-12-02T10:00:00",
    },
    {
        "id": "conv-3",
        "title": "TITLE-THREE",
        "gizmo_id": "g-xyz",
        "conversation_template_id": None,
        "is_archived": True,
        "create_time": None,
    },
    {
        "id": 4,
        "conversation_template_id": "tmpl-x",
        "update_time": 1700000000,
        "create_time": "TIME-TEXT",
    },
    {
        "id": "conv-5",
        "title": "TITLE-FIVE",
        "gizmo_id": None,
        "is_archived": False,
        "conversation_template_id": None,
        "update_time": "2026-01-03T00:00:00-05:00",
        "create_time": "2025-12-03T10:00:00.25",
    },
]


def test_page_script_returns_counts_and_never_content():
    out = run_page_script([SESSION, listing(ITEMS, 5)], offset=200)
    value, calls = out["value"], out["calls"]
    assert value == {
        "ok": True,
        "session_status": 200,
        "status": 200,
        "keys": ["items", "limit", "offset", "total"],
        "keys_count": 4,
        "total": 5,
        "offset": 0,
        "limit": 100,
        "items_length": 5,
        "counts": {
            "gizmo_id": {
                "null": 2,
                "project_prefix": 1,
                "other_string": 1,
                "missing": 1,
            },
            "gizmo_and_template": {
                "neither": 2,
                "both": 1,
                "gizmo_id_only": 1,
                "template_id_only": 1,
            },
            "is_archived": {"false": 3, "true": 1, "missing": 1},
            "update_time": {
                "z": 1,
                "z+fraction": 1,
                "missing": 1,
                "not_string": 1,
                "offset": 1,
            },
            "create_time": {
                "offset+fraction": 1,
                "no_offset": 1,
                "null": 1,
                "string_not_iso8601": 1,
                "no_offset+fraction": 1,
            },
            "title": {"string": 3, "null": 1, "missing": 1},
            "id": {"string": 4, "other": 1},
        },
    }
    serialised = json.dumps(value)
    for secret in (
        TOKEN,
        "SESSION-SECRET",
        "TITLE",
        "conv-",
        "g-p-abc",
        "TIME-TEXT",
        "tmpl-x",
        "2025",
    ):
        assert secret not in serialised
    assert [call["path"] for call in calls] == [
        "/api/auth/session",
        "/backend-api/conversations?offset=200&limit=100&order=updated",
    ]
    assert all(call["method"] == "GET" and call["body"] is None for call in calls)
    assert calls[0]["auth"] is None
    assert calls[1]["auth"] == f"Bearer {TOKEN}"


def test_page_script_reports_429_with_retry_after():
    out = run_page_script(
        [SESSION, listing([], 0, status=429, headers={"Retry-After": "12"})]
    )
    assert out["value"] == {
        "ok": False,
        "stage": "list",
        "status": 429,
        "retry_after": 12,
        "error": "http",
    }


def test_page_script_stops_without_a_token():
    session = {"prefix": "/api/auth/session", "status": 200, "body": {"user": None}}
    out = run_page_script([session, listing(ITEMS, 4)])
    assert out["value"] == {
        "ok": False,
        "stage": "session",
        "status": 200,
        "error": "no_token",
    }
    assert len(out["calls"]) == 1


def test_page_script_refuses_another_origin():
    out = run_page_script([SESSION, listing(ITEMS, 4)], origin="chrome-extension://x")
    assert out["value"] == {"ok": False, "stage": "origin", "error": "wrong_origin"}
    assert out["calls"] == []


def test_page_script_times_out_its_own_requests():
    hang = {"prefix": "/backend-api/conversations", "hang": True}
    out = run_page_script([SESSION, hang], timeout_ms=50)
    assert out["value"] == {"ok": False, "stage": "list", "error": "timeout"}


def test_page_script_reports_network_failures():
    out = run_page_script([{"prefix": "/api/auth/session", "reject": True}])
    assert out["value"] == {"ok": False, "stage": "session", "error": "network"}


def test_page_script_rejects_a_non_object_listing():
    route = {"prefix": "/backend-api/conversations", "status": 200, "body": [1, 2]}
    out = run_page_script([SESSION, route])
    assert out["value"] == {
        "ok": False,
        "stage": "list",
        "status": 200,
        "error": "not_a_json_object",
    }


# The command line


def test_main_prints_the_summary_and_exits_zero(monkeypatch, capsys):
    fake = FakeRemaldi({0: [completed(evaluated(page_value(0, 3, 3)))]})
    monkeypatch.setattr(poc, "run_remaldi", fake)
    monkeypatch.setattr(poc, "find_remaldi", lambda name: name)
    assert poc.main(["--target", TARGET, "--remaldi", "/opt/remaldi"]) == 0
    out = capsys.readouterr().out
    assert "stop: reached_total after 1 pages" in out
    assert fake.commands[0][:4] == ["/opt/remaldi", "evaluate", "--target", TARGET]


def test_main_exits_non_zero_when_a_page_fails(monkeypatch):
    stderr = json.dumps({"error": {"code": "target_unavailable", "message": "m"}})
    fake = FakeRemaldi({0: [completed(stderr=stderr, returncode=1)]})
    monkeypatch.setattr(poc, "run_remaldi", fake)
    monkeypatch.setattr(poc, "find_remaldi", lambda name: name)
    assert poc.main(["--target", TARGET]) == 1


def test_main_reports_a_missing_remaldi(monkeypatch):
    monkeypatch.setattr(poc.shutil, "which", lambda _name: None)
    with pytest.raises(SystemExit, match="error: nope not found"):
        poc.main(["--target", TARGET, "--remaldi", "nope"])


def test_target_defaults_to_the_only_chatgpt_tab(monkeypatch):
    monkeypatch.delenv("REMALDI_ENDPOINT", raising=False)
    tabs = [{"id": "ONLY", "type": "page", "url": "https://chatgpt.com/"}]
    monkeypatch.setattr(poc, "list_devtools_targets", lambda _endpoint: tabs)
    assert poc.resolve_target(None) == "ONLY"
    assert poc.resolve_target("EXPLICIT") == "EXPLICIT"


@pytest.mark.parametrize("count", [0, 2])
def test_target_must_be_unambiguous(monkeypatch, count):
    monkeypatch.delenv("REMALDI_ENDPOINT", raising=False)
    tabs = [
        {"id": str(n), "type": "page", "url": "https://chatgpt.com/"}
        for n in range(count)
    ]
    monkeypatch.setattr(poc, "list_devtools_targets", lambda _endpoint: tabs)
    with pytest.raises(SystemExit, match=f"found {count} chatgpt.com tabs"):
        poc.resolve_target(None)


def test_target_discovery_reports_an_unreachable_browser(monkeypatch):
    monkeypatch.delenv("REMALDI_ENDPOINT", raising=False)

    def refuse(_endpoint):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(poc, "list_devtools_targets", refuse)
    with pytest.raises(SystemExit, match="remote-debugging-port"):
        poc.resolve_target(None)
