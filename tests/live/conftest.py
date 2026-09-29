"""Live-test boundary harness (Phase 4 §21, §29).

Tests in this directory are OFFLINE BY DEFAULT. They are only collected
when `RUN_LIVE_TESTS=1` is in the environment, AND only the ones for
which the host integration has wired the relevant capability / token.

The live tests verify that the production mapping — the SAME code
that's exercised by the offline tests — still produces correct output
against the real upstream. They are NOT a substitute for offline
fixture tests; they're a check that fixture parity didn't drift.

Run only what you mean to:

  RUN_LIVE_TESTS=1 \
    pytest tests/live -q -k hacker_news

  RUN_LIVE_TESTS=1 GITHUB_TOKEN=ghp_*** \
    pytest tests/live -q -k github

  RUN_LIVE_TESTS=1 REDDIT_CLIENT_ID=*** REDDIT_CLIENT_SECRET=*** \
    pytest tests/live -q -k reddit
"""
from __future__ import annotations

import os

import pytest


LIVE_FLAG = "RUN_LIVE_TESTS"

# Maps each live test file to the env-var dependencies that the host
# integration must supply for the corresponding live run. Tests consult
# this map to SKIP rather than FAIL when credentials are missing.
LIVE_DEPS = {
    "test_live_hacker_news": set(),
    "test_live_bluesky": set(),
    "test_live_github": {"GITHUB_TOKEN"},
    "test_live_reddit": {"REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"},
}


def pytest_collection_modifyitems(config, items):
    """Three-state skip rule for the live directory:

      * RUN_LIVE_TESTS unset / != "1"        → SKIP (offline by default)
      * RUN_LIVE_TESTS=1 + creds available   → RUN
      * RUN_LIVE_TESTS=1 + creds missing     → SKIP (does NOT FAIL)
    """
    flag = os.environ.get(LIVE_FLAG)
    for item in items:
        if "tests/live" not in str(item.fspath):
            continue
        if flag != "1":
            item.add_marker(pytest.mark.skip(
                reason=f"live test — set {LIVE_FLAG}=1 to enable"
            ))
            continue
        for filename, deps in LIVE_DEPS.items():
            if filename in str(item.fspath):
                missing = [d for d in deps if not os.environ.get(d)]
                if missing:
                    item.add_marker(pytest.mark.skip(
                        reason=f"missing live creds: {','.join(missing)}"
                    ))
                break
