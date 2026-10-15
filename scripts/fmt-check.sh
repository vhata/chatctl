#!/usr/bin/env bash
# Formatter in check mode. Extra arguments are passed to ruff.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --locked ruff format --check "$@" .
