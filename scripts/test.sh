#!/usr/bin/env bash
# Python tests (pytest) and the discovery probe's tests (node --test).
# Extra arguments are passed to pytest. Both suites fail when they collect
# nothing: pytest exits 5 on its own, and node is checked here because it
# exits 0 with zero tests.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "--> pytest"
uv run --locked pytest --strict-markers "$@"

echo "--> node --test discovery/"
out="$(mktemp)"
trap 'rm -f "$out"' EXIT
status=0
node --test --test-reporter=tap discovery/ > "$out" 2>&1 || status=$?
tail -n 9 "$out"
if [ "$status" -ne 0 ]; then
  cat "$out"
  exit "$status"
fi
if ! grep -Eq '^# tests [1-9][0-9]*$' "$out"; then
  echo "test: node --test collected no tests in discovery/" >&2
  exit 1
fi
