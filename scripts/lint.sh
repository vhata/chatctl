#!/usr/bin/env bash
# Linter. The rule set is pinned in pyproject.toml. Extra arguments are passed
# to ruff.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --locked ruff check "$@" .
