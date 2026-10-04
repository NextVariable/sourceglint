# Source coverage and access truth

The product target is broad recent-information discovery, not a claim that every platform exposes a broad public API. `config/source_catalog.yaml` is the complete, machine-readable coverage catalog. `config/sources.yaml` is narrower and lists runtime sources that the engine can actually attempt.

## Retrieval design

Sourceglint combines a broad source catalog with bounded routing per question,
direct adapters, optional local tools and the host's search and reasoning.
It preserves publication dates, source bodies, independently dated comments,
failures and coverage limits. Provider access restrictions still apply.
The failure-handling rules and code references are in
[the source fallback playbook](source-fallback-playbook.md).

The current native routes do not establish representative month-wide coverage.
The [dated evaluation](benchmarks/2026-10-05-competitive-retest.md) records
concentrated Reddit dates, failed community discovery and relevance gaps.

## Current callable layers

| Layer | Current examples | What “usable” means |
|---|---|---|
| Built-in direct connector | Reddit RSS, Hacker News, GitHub, YouTube, Stack Overflow, DEV, Hugging Face, npm search, Qiita, arXiv; X, Product Hunt, Bluesky and Semantic Scholar when credentialed | The repository contains and tests an adapter. The dated live snapshot distinguishes current successes from credential-blocked checks; availability can still drift. |
| Official/third-party route declared, connector not yet built | LinkedIn, Meta, app stores, ScrapeCreators and paid intelligence APIs | Technically possible under the provider's credentials, permissions, pricing and terms. Merely setting a credential does not create a connector. |
| Host web search fallback | Public pages from X, YouTube, Product Hunt, reviews, crowdfunding, news, social and local-market sites | The host can search indexed public pages and return traceable dates/URLs. Coverage may be partial and engagement/comment depth may be missing. |
| User-authorized/private | Discord, Telegram and private communities | Only content the user has authorized through a bot, MCP connector, browser session or export. No broad private-community search is claimed. |
| Owner-only official API | App Store Connect and Google Play Developer reviews | High-quality access for the user's own app. Competitor reviews require public store pages or a separately licensed provider. |

## Important platform boundaries

- YouTube has official search and comment endpoints, but search requires a project/API key and quota. The current built-in route uses local `yt-dlp` for public metadata and bounded public timed-caption retrieval, does not read browser cookies, and does not download media.
- Bluesky direct search now requires `BSKY_HANDLE` plus a revocable app password and uses the authenticated `api.bsky.app` AppView. The old anonymous mirror is not treated as usable.
- X recent/full-archive search requires X API access and a bearer token. The built-in connector tries full archive first and reports when it falls back to a seven-day recent-search window. Web-indexed posts are only a partial fallback.
- Product Hunt's built-in connector reads the recent GraphQL post feed and filters it locally by topic. Its API requires an access token and its documentation restricts commercial use without approval.
- LinkedIn post reads are organization-role or approved-member scoped. It is not a general public-post firehose.
- TikTok Research API is approval- and eligibility-restricted; commercial users cannot assume access. TikTok Creative Center is a separate public trend/ad surface.
- Discord message content is a privileged intent and the bot must be present in the server.
- Apple and Google official review APIs are owner-authorized. They do not provide unrestricted competitor-review APIs.
- Kickstarter, Makuake, GREEN FUNDING, CAMPFIRE and similar crowdfunding sources are represented through public project pages/search unless a supported commercial integration is added.
- Google Search/News are discovery routes. Final evidence must cite the original page.

## Efficiency policy

The Skill does not query every catalog source for every request. The router filters by research mode, market and language, caps host-search targets at ten, prefers local sources for a named market, limits each source family during the first selection pass, and skips sources already covered by direct connectors. A product-feedback question emphasizes communities and review stores; a market-entry question adds local news, crowdfunding, ads and professional sources; a technology-development question emphasizes developer and research ecosystems.

## Verification commands

`python scripts/audit_source_access.py --json` reports connector presence, missing credential names, local-tool availability and the last dated live-test snapshot without exposing secret values. A dated pass is not treated as permanent availability. `RUN_LIVE_TESTS=1 pytest tests/live -q` checks no-auth live connectors and runs credentialed checks only when the relevant environment variables are present. Offline tests validate catalog structure, routing limits and adapter mappings.

## Primary access documentation

- Bluesky post search: https://docs.bsky.app/docs/api/app-bsky-feed-search-posts
- YouTube search: https://developers.google.com/youtube/v3/docs/search/list
- Product Hunt API: https://api.producthunt.com/v2/docs
- LinkedIn Posts API: https://learn.microsoft.com/linkedin/marketing/community-management/shares/posts-api
- TikTok Research API: https://developers.tiktok.com/products/research-api
- Discord privileged intents: https://support-dev.discord.com/hc/en-us/articles/6207308062871-What-are-Privileged-Intents
- Apple customer reviews: https://developer.apple.com/documentation/appstoreconnectapi/customer-reviews
- Google Play reviews: https://developers.google.com/android-publisher/api-ref/rest/v3/reviews
- Meta Ad Library API: https://www.facebook.com/ads/library/api/
- Google Ads Transparency: https://support.google.com/adspolicy/answer/13733850
