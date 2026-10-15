#!/usr/bin/env bash
# Python tests (pytest) and the discovery probe's tests (node --test).
# Extra arguments are passed to pytest. Each suite must pass at least one
# test: a suite that collects nothing, or skips everything, fails here.
# pytest exits 5 on empty collection but 0 when every test is skipped, and
# node exits 0 in both cases, so both are checked from their summaries.
set -euo pipefail
cd "$(dirname "$0")/.."

out="$(mktemp)"
trap 'rm -f "$out"' EXIT

echo "--> pytest"
uv run --locked pytest --strict-markers "$@" | tee "$out"
if ! grep -Eq '(^|[^0-9])[1-9][0-9]* passed' "$out"; then
  echo "test: pytest passed no tests (all skipped or deselected?)" >&2
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
