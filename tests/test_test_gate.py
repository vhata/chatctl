"""Exercise the real test gate with disposable Python and Node suites."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EMPTY = 'require("node:test");\n'
PASS = 'require("node:test")("passes", () => {});\n'
SKIP = 'require("node:test")("skipped", {skip: true}, () => {});\n'


@pytest.mark.parametrize(
    ("sources", "accepted"),
    [
        ({}, False),
        ({"probe.test.js": EMPTY}, False),
        ({"probe.test.js": EMPTY, "other.test.js": EMPTY}, False),
        ({"probe.test.js": 'console.log("# pass 1");\n' + EMPTY}, False),
        ({"probe.test.js": SKIP}, False),
        ({"probe.test.js": EMPTY, "other.test.js": SKIP}, False),
        ({"probe.test.js": 'require("node:test").describe("empty", () => {});'}, False),
        (
            {"probe.test.js": 'require("node:test")("todo", {todo: true}, () => {});'},
            False,
        ),
        ({"probe.test.js": PASS}, True),
        ({"probe.test.js": EMPTY, "other.test.js": PASS}, True),
        (
            {
                "probe.test.js": 'require("node:test").describe("suite", () => {'
                + PASS
                + "});"
            },
            True,
        ),
        (
            {
                "probe.test.js": PASS
                + 'require("node:test")("fails", () => {throw Error("failure");});'
            },
            False,
        ),
    ],
    ids=[
        "no-files",
        "import-only",
        "multiple-empty-files",
        "printed-pass-summary",
        "all-skipped",
        "empty-and-skipped",
        "empty-describe",
        "all-todo",
        "passing-test",
        "empty-and-passing",
        "nested-passing-test",
        "passing-and-failing",
    ],
)
def test_node_gate(tmp_path: Path, sources: dict[str, str], accepted: bool):
    # Copy the gate and locked project configuration, but supply tiny suites.
    # Real uv, pytest and Node run here; nothing uses a logged-in account.
    for name in ("pyproject.toml", "uv.lock", ".python-version", "README.md"):
        shutil.copy2(ROOT / name, tmp_path / name)
    shutil.copytree(ROOT / "chatctl", tmp_path / "chatctl")
    (tmp_path / "scripts").mkdir()
    for name in ("test.sh", "node-pass-count.js"):
        shutil.copy2(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_fixture.py").write_text(
        "def test_pass():\n    assert True\n"
    )
    (tmp_path / "discovery").mkdir()
    for name, source in sources.items():
        (tmp_path / "discovery" / name).write_text(source)
    env = os.environ.copy()
    # Each fixture owns its environment, even when invoked from `uv run`.
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    result = subprocess.run(
        ["bash", str(tmp_path / "scripts" / "test.sh")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    output = result.stdout + result.stderr
    assert "1 passed" in output, output
    assert "--> node --test discovery/" in output, output
    assert (result.returncode == 0) is accepted, output
    if not accepted and "fails" not in sources.get("probe.test.js", ""):
        assert "node --test passed no tests" in output, output
