# Source failure and fallback playbook

When a platform route fails, do not immediately remove the source and do not
pretend that a web-search snippet is equivalent to direct coverage. Classify
the failure first, then inspect maintained open-source implementations and the
platform's current documentation before choosing one bounded alternate route.

## Decision order

1. Prefer an official API or documented public endpoint.
2. If the API is unavailable but a maintained local tool can read public data,
   use it without importing browser cookies or downloading unrelated content.
3. Use a user-authorized browser, MCP connector, bot, or export only for data
   the user is entitled to access.
4. Treat third-party aggregation APIs as explicit opt-in integrations. Record
   credentials, pricing, data-processing and terms constraints; never silently
   send a query to them.
5. Fall back to domain-restricted public web search. Label the result partial
   because indexing, dates, comments and engagement may be missing.

For a new workaround, confirm that the upstream repository is active, inspect
its source rather than copying README claims, check recent issues for breakage,
and add an offline adapter test plus an opt-in live check. A route becomes
"working" only after a live check succeeds in the current environment.

## Findings from open-source competitors

The current Last 30 Days implementation is the most useful source-specific
reference. Its code uses multiple routes per platform rather than one universal
scraper:

- Bluesky: create an app-password session at `bsky.social`, then query the
  canonical authenticated `api.bsky.app` AppView. Its source explicitly says
  the older `public.api.bsky.app` search mirror is blocked. This project now
  implements the same protocol shape, without copying or storing credentials.
- YouTube: run `yt-dlp` locally for search metadata and transcripts, bound
  concurrency and timeouts, then optionally fall back to a paid provider only
  on genuine failures. This project now implements the smaller metadata-only
  path: no browser cookies and no media download.
- Reddit: its keyless path combines RSS, public listing fragments, comment-page
  parsing and an archive service, then uses a paid API only when the free lanes
  fail. This project now implements and live-tests the smaller public RSS lane.
  It keeps OAuth as an optional richer route and explicitly does not claim RSS
  engagement or full-comment coverage.
- X: its alternatives include X's authenticated `xurl` CLI, an authenticated
  browser-cookie client, xAI search and third-party APIs. This project records
  the official CLI route but does not import browser cookies by default.
- TikTok, Instagram, Threads and LinkedIn: the competitor uses ScrapeCreators.
  That is a paid third-party processor, not a public platform API. The catalog
  records it as optional and unimplemented, so its existence cannot be mistaken
  for current coverage.

Primary implementation references:


These references are design evidence, not a guarantee that their routes still
work from every host. Recheck source, issues and live behavior when a failure
occurs; platforms change independently of this repository.

Other projects reinforce the separation between discovery and extraction.
`lukeswade/deep-research` discovers through SearXNG, then uses YouTube captions
and Reddit thread JSON for deeper reading; for general web bot walls it can
escalate to Chrome TLS impersonation and an optional browser sidecar. Those
browser-escalation methods are not automatic here because they add deployment,
terms and security cost; a host-authorized browser remains the explicit route.
project's decision to keep vendor-specific tools outside the deterministic
research core whenever possible.

- https://github.com/lukeswade/deep-research
