"""Read-only remaldi transport, adapted from discovery/transport_poc.py.

The caller supplies an explicit tab target. Credentials stay in the page;
listing JSON crosses the boundary as text so Python can reject duplicate
keys before JavaScript's JSON parser can erase them. No target discovery or
browser startup happens here.
"""

import json
import math
import subprocess
from collections.abc import Callable, Sequence
from typing import cast

PAGE_TIMEOUT_MS = 4000
RUNNER_TIMEOUT_SECONDS = 30.0
UNKNOWN_OUTCOME_GRACE_SECONDS = PAGE_TIMEOUT_MS / 1000 + 1


class ClientError(Exception):
    """A safe diagnostic containing no response body or subprocess output."""

    def __init__(
        self,
        kind: str,
        *,
        retryable: bool = False,
        status: int | None = None,
        retry_after: float | None = None,
        uncertain: bool = False,
    ) -> None:
        self.kind = kind
        self.retryable = retryable
        self.status = status
        self.retry_after = retry_after
        self.uncertain = uncertain
        super().__init__(kind if status is None else f"{kind} (HTTP {status})")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            # Neither the key nor the body is safe to include in an error.
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError("non-finite JSON number")


def decode_json(raw: str) -> object:
    """Decode strict JSON, rejecting duplicate keys at every nesting level."""
    try:
        return cast(
            object,
            json.loads(
                raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
            ),
        )
    except (ValueError, RecursionError):
        raise ClientError("invalid_json") from None


PAGE_SCRIPT = """(async () => {
  "use strict";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), __TIMEOUT_MS__);
  async function get(path, token) {
    const headers = token === null ? {} : { Authorization: `Bearer ${token}` };
    return await fetch(path, { method: "GET", headers, signal: controller.signal });
  }
  function httpFailure(response) {
    const raw = response.headers.get("retry-after");
    const seconds = raw === null || raw.trim() === "" ? NaN : Number(raw);
    return { ok: false, error: "http", status: response.status,
      retry_after: Number.isFinite(seconds) && seconds >= 0 ? seconds : null };
  }
  try {
    if (location.origin !== "https://chatgpt.com") {
      return { ok: false, error: "wrong_origin" };
    }
    const session = await get("/api/auth/session", null);
    if (session.status !== 200) return httpFailure(session);
    let token;
    try {
      token = (await session.json())?.accessToken;
    } catch {
      return { ok: false, error: controller.signal.aborted ? "timeout" : "session_json" };
    }
    if (typeof token !== "string" || token === "") {
      return { ok: false, error: "no_token" };
    }
    const response = await get(
      "/backend-api/conversations?offset=__OFFSET__&limit=__LIMIT__&order=updated__ARCHIVED__", token);
    token = null;
    if (response.status !== 200) return httpFailure(response);
    // Do not parse this JSON here: JSON.parse silently accepts duplicate keys.
    return { ok: true, body: await response.text() };
  } catch {
    // Exception messages can contain tokens, titles or response content.
    return { ok: false, error: controller.signal.aborted ? "timeout" : "network" };
  } finally {
    clearTimeout(timer);
  }
})()"""


def build_page_expression(offset: int, limit: int, *, archived: bool = False) -> str:
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    if type(archived) is not bool:
        raise ValueError("archived must be a boolean")
    return (
        PAGE_SCRIPT.replace("__OFFSET__", str(offset))
        .replace("__LIMIT__", str(limit))
        .replace("__TIMEOUT_MS__", str(PAGE_TIMEOUT_MS))
        .replace("__ARCHIVED__", "&is_archived=true" if archived else "")
    )


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=RUNNER_TIMEOUT_SECONDS,
        check=False,
    )


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class RemaldiTransport:
    """One session GET and at most one listing GET per evaluation.

    No retries here: ConversationClient owns pacing and bounded retries.
    A fresh session lookup avoids storing tokens on the page or in Python.
    """

    def __init__(
        self,
        target: str,
        *,
        archived: bool = False,
        remaldi: str = "remaldi",
        run: Runner = _run,
    ) -> None:
        if not target.strip() or target.startswith("-"):
            raise ValueError("an explicit tab target is required")
        if type(archived) is not bool:
            raise ValueError("archived must be a boolean")
        self.target = target
        self.remaldi = remaldi
        self._run = run
        self._archived = archived

    def get_page(self, offset: int, limit: int) -> str:
        command = [
            self.remaldi,
            "evaluate",
            "--target",
            self.target,
            "--await-promise",
            "--return-by-value",
            "--",
            build_page_expression(offset, limit, archived=self._archived),
        ]
        try:
            result = self._run(command)
        except subprocess.TimeoutExpired:
            raise ClientError(
                "runner_timeout", retryable=True, uncertain=True
            ) from None
        except (OSError, UnicodeError):
            raise ClientError("runner_error") from None
        if result.returncode != 0:
            # Read only the known code, never echo remaldi's message or stderr.
            try:
                error = decode_json(result.stderr)
            except ClientError:
                error = None
            if isinstance(error, dict):
                detail = error.get("error")
                if isinstance(detail, dict) and detail.get("code") == "unknown_outcome":
                    raise ClientError(
                        "remaldi_unknown_outcome", retryable=True, uncertain=True
                    )
            raise ClientError("remaldi_error")
        output = decode_json(result.stdout)
        if not isinstance(output, dict) or "exceptionDetails" in output:
            raise ClientError("remaldi_output")
        remote = output.get("result")
        if not isinstance(remote, dict):
            raise ClientError("remaldi_output")
        value = remote.get("value")
        if not isinstance(value, dict):
            raise ClientError("remaldi_output")
        if value.get("ok") is True:
            body = value.get("body")
            if not isinstance(body, str):
                raise ClientError("remaldi_output")
            return body
        kind = value.get("error")
        if kind == "http":
            status = value.get("status")
            if type(status) is not int or not 100 <= status <= 599:
                raise ClientError("remaldi_output")
            raw_delay = value.get("retry_after")
            delay = None
            if (
                isinstance(raw_delay, int | float)
                and not isinstance(raw_delay, bool)
                and raw_delay >= 0
            ):
                # Cap before conversion so even a huge JSON integer is safe.
                capped = float(min(raw_delay, 60))
                if math.isfinite(capped):
                    delay = capped
            raise ClientError(
                "http",
                status=status,
                retryable=status == 429 or status >= 500,
                retry_after=delay,
            )
        if kind in ("timeout", "network"):
            raise ClientError(kind, retryable=True)
        if kind in ("wrong_origin", "session_json", "no_token"):
            raise ClientError(kind)
        raise ClientError("remaldi_output")
