#!/usr/bin/env python3
"""Print a secret-free snapshot of configured research-source access."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from pathlib import Path

import yaml

from gtm_intelligence.source_catalog import load_source_catalog


BUILT_IN_CONNECTORS = {
    "arxiv", "bluesky", "devto", "github", "hacker_news", "hugging_face",
    "package_registries", "qiita", "reddit", "semantic_scholar",
    "stack_overflow", "youtube",
}
LOCAL_TOOL_REQUIREMENTS = {"youtube": "yt-dlp"}


def build_report() -> dict[str, object]:
    catalog = load_source_catalog()
    live_status_path = Path(__file__).resolve().parents[1] / "docs" / "source-live-status.json"
    live_status = {}
    if live_status_path.exists():
        live_status = json.loads(live_status_path.read_text(encoding="utf-8"))
    live_passed = set(live_status.get("passed") or [])
    live_skipped = live_status.get("skipped") or {}
    runtime_config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "config" / "sources.yaml").read_text(
            encoding="utf-8"
        )
    )
    runtime_enabled = {
        str(item["name"]): bool(item.get("enabled")) for item in runtime_config
    }
    direct = []
    credential_routes = []
    for source in catalog:
        missing = [name for name in source.credentials if not os.environ.get(name)]
        if source.name in BUILT_IN_CONNECTORS:
            local_tool = LOCAL_TOOL_REQUIREMENTS.get(source.name)
            direct.append({
                "source": source.name,
                "connector_implemented": True,
                "runtime_enabled": runtime_enabled.get(source.name, False),
                "credentials_configured": not missing,
                "missing_credentials": missing,
                "local_tool": local_tool,
                "local_tool_available": (
                    bool(shutil.which(local_tool)) if local_tool else None
                ),
                "live_verified": source.name in live_passed,
                "live_verified_at": (
                    live_status.get("verified_at") if source.name in live_passed else None
                ),
                "live_blocked_by": live_skipped.get(source.name, []),
            })
        elif source.credentials:
            credential_routes.append({
                "source": source.name,
                "route_implemented": False,
                "credentials_present": not missing,
                "missing_credentials": missing,
            })
    return {
        "catalog_sources": len(catalog),
        "availability": dict(sorted(Counter(x.availability for x in catalog).items())),
        "host_search_candidates": sum("host_web_search" in x.routes for x in catalog),
        "built_in_connectors": direct,
        "declared_credential_routes": credential_routes,
        "important_boundary": (
            "A catalog entry or present credential does not imply an implemented connector. "
            "Public-web fallback coverage depends on the host search capability and indexing."
        ),
        "live_snapshot": {
            "verified_at": live_status.get("verified_at"),
            "passed": sorted(live_passed),
            "skipped": live_skipped,
            "staleness_warning": live_status.get("note"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"catalog sources: {report['catalog_sources']}")
        print(f"host-search candidates: {report['host_search_candidates']}")
        for item in report["built_in_connectors"]:
            state = "configured" if item["credentials_configured"] else "missing credentials"
            if item["local_tool"] and not item["local_tool_available"]:
                state = f"missing local tool {item['local_tool']}"
            print(f"built-in {item['source']}: {state}")
        print(report["important_boundary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
