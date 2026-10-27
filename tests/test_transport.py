"""Exercise remaldi and page JavaScript entirely behind fake boundaries."""

import json
import shutil
import subprocess
from collections.abc import Sequence

import pytest

from chatctl.client import ConversationClient
from chatctl.transport import ClientError, RemaldiTransport, build_page_expression


def completed(
    value: object, *, code: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        [], code, json.dumps({"result": {"value": value}}), stderr
    )


def test_explicit_command_and_round_trip_raw_body():
    calls: list[Sequence[str]] = []
    raw = '{"items": [], "offset": 0, "limit": 100, "total": 0}'

    def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return completed({"ok": True, "body": raw})

    transport = RemaldiTransport("placeholder-tab", run=run)
    assert ConversationClient(transport).list_conversations() == ()
    assert list(calls[0][:-1]) == [
        "remaldi",
        "evaluate",
        "--target",
        "placeholder-tab",
        "--await-promise",
        "--return-by-value",
        "--",
    ]
    assert calls[0][-1] == build_page_expression(0, 100)


@pytest.mark.parametrize("target", ["", " ", "--target"])
def test_target_required(target):
    with pytest.raises(ValueError):
        RemaldiTransport(target)


@pytest.mark.parametrize(
    "offset,limit", [(-1, 100), (True, 100), (0, 0), (0, 101), (0, True)]
)
def test_expression_arguments_are_numeric(offset, limit):
    with pytest.raises(ValueError):
        build_page_expression(offset, limit)


@pytest.mark.parametrize(
    "status,retryable",
    [
        (401, False),
        (403, False),
        (404, False),
        (429, True),
        (500, True),
        (503, True),
        (599, True),
    ],
)
def test_http_errors_and_retry_after(status, retryable):
    result = completed(
        {"ok": False, "error": "http", "status": status, "retry_after": 1000}
    )
    with pytest.raises(ClientError) as caught:
        RemaldiTransport("tab", run=lambda _: result).get_page(0, 100)
    assert caught.value.status == status
    assert caught.value.retryable is retryable
    assert caught.value.retry_after == 60


@pytest.mark.parametrize(
    "value,expected",
    [(None, None), (True, None), (-1, None), ("secret", None), (0, 0), (12, 12)],
)
def test_retry_after_validation(value, expected):
    result = completed(
        {"ok": False, "error": "http", "status": 429, "retry_after": value}
    )
    with pytest.raises(ClientError) as caught:
        RemaldiTransport("tab", run=lambda _: result).get_page(0, 100)
    assert caught.value.retry_after == expected


@pytest.mark.parametrize(
    "kind,retryable",
    [
        ("network", True),
        ("timeout", True),
        ("wrong_origin", False),
        ("no_token", False),
        ("session_json", False),
        ("secret", False),
    ],
)
def test_page_failures_are_sanitized(kind, retryable):
    result = completed({"ok": False, "error": kind, "message": "secret"})
    with pytest.raises(ClientError) as caught:
        RemaldiTransport("tab", run=lambda _: result).get_page(0, 100)
    assert caught.value.retryable is retryable
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "stdout",
    [
        "secret",
        "[]",
        "{}",
        '{"exceptionDetails":{"text":"secret"}}',
        '{"result":{"value":{"ok":true,"body":5}}}',
        '{"result":{"value":{"ok":true,"body":"{}","body":"secret"}}}',
    ],
)
def test_invalid_remaldi_output_is_safe(stdout):
    result = subprocess.CompletedProcess([], 0, stdout, "secret")
    with pytest.raises(ClientError) as caught:
        RemaldiTransport("tab", run=lambda _: result).get_page(0, 100)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "code,retryable",
    [("unknown_outcome", True), ("invalid_target", False), ("secret", False)],
)
def test_remaldi_errors(code, retryable):
    result = completed(
        None, code=1, stderr=json.dumps({"error": {"code": code, "message": "secret"}})
    )
    with pytest.raises(ClientError) as caught:
        RemaldiTransport("tab", run=lambda _: result).get_page(0, 100)
    assert caught.value.retryable is retryable
    assert caught.value.uncertain is retryable
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "error,retryable",
    [
        (FileNotFoundError("secret"), False),
        (subprocess.TimeoutExpired("secret", 30, output="secret"), True),
    ],
)
def test_runner_failure(error, retryable):
    def run(_: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise error

    with pytest.raises(ClientError) as caught:
        RemaldiTransport("tab", run=run).get_page(0, 100)
    assert caught.value.retryable is retryable
    assert "secret" not in str(caught.value)


def test_default_runner_uses_bounded_subprocess(monkeypatch):
    calls: list[dict[str, object]] = []

    def run(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return completed({"ok": True, "body": "{}"})

    monkeypatch.setattr(subprocess, "run", run)
    assert RemaldiTransport("tab").get_page(0, 100) == "{}"
    assert calls == [
        {"capture_output": True, "text": True, "timeout": 30, "check": False}
    ]


# Node evaluates only the generated JavaScript. No real fetch is installed.
def execute_page(
    *, origin: str = "https://chatgpt.com", scenario: str = "ok", timeout_ms: int = 4000
) -> dict[str, object]:
    node = shutil.which("node")
    assert node is not None, "Node is required for page-script validation"
    script = build_page_expression(100, 100).replace("4000", str(timeout_ms))
    harness = r"""
const calls = [];
const scenario = __SCENARIO__;
globalThis.location = {origin: __ORIGIN__};
globalThis.fetch = async (path, options) => {
  calls.push({path, method: options.method, headers: options.headers, body: options.body ?? null});
  if (scenario === "network") throw new Error("secret");
  if (scenario === "timeout") return await new Promise((_, reject) => {
    options.signal.addEventListener("abort", () => reject(new Error("secret")));
  });
  const session = path === "/api/auth/session";
  const status = scenario === "http" ? 429 : 200;
  return {
    status, headers: {get: () => "12"},
    json: async () => {
      if (!session) throw new Error("listing must be read as text");
      if (scenario === "session_json") throw new Error("secret");
      return {accessToken: scenario === "no_token" ? "" : "secret", sessionToken:"secret"};
    },
    text: async () => '{"items":[{"gizmo_id":"g-p-placeholder","gizmo_id":null}],"offset":100,"limit":100,"total":101}',
  };
};
(async () => {
  const value = await __SCRIPT__;
  console.log(JSON.stringify({value, calls}));
})();
"""
    harness = (
        harness.replace("__SCENARIO__", json.dumps(scenario))
        .replace("__ORIGIN__", json.dumps(origin))
        .replace("__SCRIPT__", script)
    )
    result = subprocess.run(
        [node, "-e", harness], capture_output=True, text=True, timeout=5, check=True
    )
    value: dict[str, object] = json.loads(result.stdout)
    return value


def test_page_uses_get_only_and_preserves_duplicate_json():
    result = execute_page()
    calls = result["calls"]
    assert isinstance(calls, list) and len(calls) == 2
    assert [c["method"] for c in calls] == ["GET", "GET"]
    assert all(c["body"] is None for c in calls)
    assert calls[0]["headers"] == {}
    assert calls[1]["headers"] == {"Authorization": "Bearer secret"}
    assert (
        calls[1]["path"]
        == "/backend-api/conversations?offset=100&limit=100&order=updated"
    )
    value = result["value"]
    assert isinstance(value, dict) and value["ok"] is True
    assert "secret" not in json.dumps(value)
    transport = RemaldiTransport("tab", run=lambda _: completed(value))
    with pytest.raises(ClientError, match="invalid_json"):
        ConversationClient(transport).list_conversations()


@pytest.mark.parametrize(
    "origin", ["vivaldi://browser", "https://chatgpt.com.evil", "http://chatgpt.com"]
)
def test_page_checks_origin_before_any_fetch(origin):
    result = execute_page(origin=origin)
    assert result == {"value": {"ok": False, "error": "wrong_origin"}, "calls": []}


@pytest.mark.parametrize(
    "scenario", ["network", "timeout", "session_json", "no_token", "http"]
)
def test_page_errors_and_abort_are_safe(scenario):
    result = execute_page(scenario=scenario, timeout_ms=5)
    value = result["value"]
    assert isinstance(value, dict) and value["ok"] is False
    assert value["error"] == scenario
    assert "secret" not in json.dumps(value)
    calls = result["calls"]
    assert isinstance(calls, list) and len(calls) == 1
