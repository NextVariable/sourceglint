"""Phase 7 §25–§26 — default runtime wiring for the canonical API/CLI.

The core engine is host-neutral; a host injects the model and (usually)
its own adapters. This module provides the *defaults* used when a caller
does not inject anything:

* ``default_sources``       — raw source-registry entries from
  ``config/sources.yaml`` (repository layout) with credential-NAME-only
  contract; absent file → empty registry (no crash).
* ``default_adapter_factory`` — maps a registry source name onto its
  connector adapter. Credentials are read from the environment as NAMES
  only inside the adapters; this factory never logs a value (§25).
  Sources without a concrete connector resolve to None (skipped with a
  coverage note — capability discovery at runtime, never hardcoded in
  prompts, §26).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping
from ..resources import data_path

_REPO_CONFIG = data_path("config", "sources.yaml")
_ENV_CONFIG = os.environ.get("GTM_INTELLIGENCE_SOURCES_YAML", "")


def default_sources() -> list[dict[str, Any]]:
    """Raw registry entries for default runs. Empty list when the config
    file cannot be resolved (package-relative fallback honored)."""
    import yaml

    candidates = [_ENV_CONFIG, str(_REPO_CONFIG)]
    for cand in candidates:
        if not cand:
            continue
        path = Path(cand)
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if isinstance(data, list):
            return data
    return []


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    return ""


def default_adapter_factory(
    name: str, plan: Mapping[str, Any]
) -> Any | None:
    """Map registry source name → connector adapter instance.

    Returns None for sources with no concrete connector in this repo or
    no host-provided capability — the ResearchPipeline records them as
    UNAVAILABLE with a credential-name-only warning (§25, §26).
    """
    from ..connectors.github import GitHubAdapter
    from ..connectors.hacker_news import HackerNewsAdapter
    from ..connectors.reddit import RedditAdapter
    from ..connectors.bluesky import BlueskyAdapter
    from ..connectors.youtube import YouTubeAdapter
    from ..connectors.open_sources import (
        ArxivAdapter,
        DevToAdapter,
        HuggingFaceAdapter,
        PackageRegistriesAdapter,
        QiitaAdapter,
        SemanticScholarAdapter,
        StackOverflowAdapter,
    )
    from ..connectors.authorized_sources import ProductHuntAdapter, XAdapter

    if name == "bluesky":
        return BlueskyAdapter(
            handle=_env("BSKY_HANDLE") or None,
            app_password=_env("BSKY_APP_PASSWORD") or None,
        )
    if name == "youtube":
        return YouTubeAdapter()
    if name == "hacker_news":
        return HackerNewsAdapter()
    if name == "github":
        token = _env("GITHUB_TOKEN")
        return GitHubAdapter(token=token or None)
    if name == "reddit":
        return RedditAdapter(
            client_id=_env("REDDIT_CLIENT_ID", "REDDIT_CLIENT_ID") or None,
            client_secret=_env("REDDIT_CLIENT_SECRET") or None,
            allow_keyless_rss=True,
        )
    public_adapters = {
        "arxiv": ArxivAdapter,
        "devto": DevToAdapter,
        "hugging_face": HuggingFaceAdapter,
        "package_registries": PackageRegistriesAdapter,
        "qiita": QiitaAdapter,
        "stack_overflow": StackOverflowAdapter,
    }
    adapter_type = public_adapters.get(name)
    if adapter_type is not None:
        return adapter_type()
    if name == "semantic_scholar":
        return SemanticScholarAdapter(
            api_key=_env("SEMANTIC_SCHOLAR_API_KEY") or None,
        )
    if name == "x":
        return XAdapter(bearer_token=_env("X_BEARER_TOKEN") or None)
    if name == "product_hunt":
        return ProductHuntAdapter(token=_env("PRODUCT_HUNT_TOKEN") or None)
    # official_web and host_web_search need a host search/fetch capability
    # or an official-fetch connector — not present standalone in this repo.
    return None
