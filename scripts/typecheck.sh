#!/usr/bin/env bash
# Type checker. mypy's strictness, Python version and paths (chatctl/ and
# tests/) are pinned in pyproject.toml. Extra arguments are passed to mypy.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --locked mypy "$@"
