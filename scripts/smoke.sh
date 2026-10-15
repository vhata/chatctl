#!/usr/bin/env bash
# Cheapest end-to-end exercise: the installed console script starts, reports
# its version and prints help. Catches a broken [project.scripts] entry or
# package layout that unit tests importing chatctl directly would miss.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --locked chatctl --version
uv run --locked chatctl --help > /dev/null
echo "smoke: chatctl entry point OK"
