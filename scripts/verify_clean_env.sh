#!/usr/bin/env bash
# Clean-environment verification (Phase 5 verification closeout).
#
# Builds a FRESH virtualenv (never reuses .venv), installs the package
# with dev extras, then runs the full suite once. Owned by developers /
# CI — no test file inside the repo calls this.
#
# Usage:
#   scripts/verify_clean_env.sh [pytest args...]
#
# Exit code: 0 only when install + full suite succeed (skips allowed,
# failures not).
set -euo pipefail

cd "$(dirname "$0")/.."

PY_BIN="${PYTHON:-python3}"
FRESH="$(mktemp -d)/venv"

echo "==> fresh venv: $FRESH"
"$PY_BIN" -m venv "$FRESH"
"$FRESH/bin/python" -m pip install --quiet --upgrade pip
"$FRESH/bin/python" -m pip install --quiet -e ".[dev]"

echo "==> python: $("$FRESH/bin/python" -c 'import sys; print(sys.version.split()[0])')"

RUN_DIR=".pytest_tmp/cleanenv-$(date +%s)-$$"
mkdir -p "$RUN_DIR"
trap 'rm -rf "$RUN_DIR" "$(dirname "$FRESH")"' EXIT

exec "$FRESH/bin/python" -m pytest tests/ -q \
    --basetemp="$PWD/$RUN_DIR/basetemp" "$@"
