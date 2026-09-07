#!/usr/bin/env bash
# Full-suite verification (Phase 5 verification closeout).
#
# This is the SINGLE owner of "run the whole suite once". Review gates
# inside tests/ never start another pytest — that guarantee lives in the
# Phase 4/5 gate files and is enforced by code review; the actual
# integrated run belongs to the developer / CI via this script.
#
# Usage:
#   scripts/verify_full_suite.sh          # run everything under tests/
#   scripts/verify_full_suite.sh -q       # quieter output (recommended)
#
# Exit code: 0 only when the whole suite passes (skips allowed, failures
# not). Live tests default to SKIP — export RUN_LIVE_TESTS=1 plus the
# credentials documented in tests/live/conftest.py to enable them.
set -euo pipefail

cd "$(dirname "$0")/.."

# Local scratch root for this run's temp dirs; kept inside the repo so
# sandboxed pytest never touches /private/var tmp roots. Gitignored.
RUN_DIR=".pytest_tmp/verify-$(date +%s)-$$"
mkdir -p "$RUN_DIR"
trap 'rm -rf "$RUN_DIR"' EXIT

exec "$PWD/.venv/bin/python" -m pytest tests/ -q \
    --basetemp="$PWD/$RUN_DIR/basetemp" "$@"
