#!/usr/bin/env bash
# Verify committed checkout installation without platform credentials or local venv.
# Artifacts are retained for inspection; this is not a live research quality test.
set -euo pipefail
cd "$(dirname "$0")/.."
PY_BIN="${PYTHON:-python3}"
CHECK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sourceglint-install.XXXXXX")"
mkdir -p "$CHECK_DIR/checkout"
git archive HEAD | tar -x -C "$CHECK_DIR/checkout"
"$PY_BIN" -m venv "$CHECK_DIR/venv"
echo "Install verification artifacts: $CHECK_DIR"
env -i PATH="$PATH" "$CHECK_DIR/venv/bin/python" -m pip install -e "$CHECK_DIR/checkout[dev]"
cd "$CHECK_DIR/checkout"
env -i PATH="$PATH" "$CHECK_DIR/venv/bin/python" -m sourceglint --help
env -i PATH="$PATH" "$CHECK_DIR/venv/bin/python" -c '
from sourceglint.pipeline.source_registry import load_registry
registry = load_registry(path="config/sources-host.yaml")
assert registry.entries
assert all(not item.auth_required and not item.credentials for item in registry.entries)
print("First-run configuration requires no platform credentials")
'
env -i PATH="$PATH" "$CHECK_DIR/venv/bin/python" -m pytest tests/ -q
echo "PASS: clean committed checkout installed and offline suite completed. Live research quality remains a separate gate."
