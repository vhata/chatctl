#!/usr/bin/env bash
# Python tests (pytest) and the discovery probe's tests (node --test).
# Extra arguments are passed to pytest, except --junitxml and
# -p no:junitxml, which would break the pass count below. Each suite must
# pass at least one test: a suite that collects nothing, or skips
# everything, fails here.
# pytest exits 5 on empty collection but 0 when every test is skipped, so
# its JUnit report is checked; node exits 0 in both cases, so its TAP
# summary is checked.
set -euo pipefail
cd "$(dirname "$0")/.."

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
out="$tmp/out"

echo "--> pytest"
uv run --locked pytest --strict-markers --junitxml="$tmp/junit.xml" "$@"
passed="$(uv run --locked python - "$tmp/junit.xml" <<'PY'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
total = 0
for s in suites:
    counts = [int(s.get(k, 0)) for k in ("tests", "errors", "failures", "skipped")]
    total += counts[0] - sum(counts[1:])
print(total)
PY
)"
if [ "$passed" -lt 1 ]; then
  echo "test: pytest passed no tests (all skipped, or a collect-only run)" >&2
  exit 1
fi

echo "--> node --test discovery/"
status=0
node --test --test-reporter=tap discovery/ > "$out" 2>&1 || status=$?
if [ "$status" -ne 0 ]; then
  cat "$out"
  exit "$status"
fi
tail -n 9 "$out"
if ! grep -Eq '^# pass [1-9][0-9]*$' "$out"; then
  echo "test: node --test passed no tests in discovery/ (none found, or all skipped)" >&2
  exit 1
fi
