#!/usr/bin/env python3
"""Print a secret-free snapshot of configured research-source access."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

import yaml

from gtm_intelligence.source_catalog import load_source_catalog


BUILT_IN_CONNECTORS = {"bluesky", "github", "hacker_news", "reddit"}


def build_report() -> dict[str, object]:
    catalog = load_source_catalog()
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
            direct.append({
                "source": source.name,
                "connector_implemented": True,
                "runtime_enabled": runtime_enabled.get(source.name, False),
                "credentials_configured": not missing,
                "missing_credentials": missing,
                "live_verified": None,
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
            print(f"built-in {item['source']}: {state}")
        print(report["important_boundary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
