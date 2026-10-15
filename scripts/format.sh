#!/usr/bin/env bash
# Formatter in write mode, plus ruff's safe autofixes (import sorting).
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --locked ruff format "$@" .
uv run --locked ruff check --fix-only .
