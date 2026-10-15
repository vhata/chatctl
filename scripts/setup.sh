#!/usr/bin/env bash
# Prepare this worktree: install dependencies from the lockfile into this
# worktree's own .venv and point git at the tracked hooks in .githooks/.
# Idempotent; run after cloning, creating a worktree, or changing hooks.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --locked

# core.hooksPath is relative, so every worktree runs its own checkout of
# .githooks/.
git config core.hooksPath .githooks

echo "setup: done. Run 'bash scripts/check.sh' to verify the baseline."
