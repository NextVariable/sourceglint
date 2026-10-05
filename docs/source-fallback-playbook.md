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

## Source-specific routes

Use [the access matrix](source-access-matrix.md) for maintained capabilities and
[the source guides](sources/host-web-search.md) for host integration. Route failures
must preserve already retrieved evidence and disclose the missing depth.

Bluesky requires an authorized app-password session and an authenticated AppView.
YouTube uses local `yt-dlp` for public metadata and attempts public captions.
Reddit can use RSS and public archive enrichment, with OAuth as an optional route.
GitHub and Hacker News retrieve bounded discussions and dated comments.
A successful parent search does not establish complete comment coverage.

X, TikTok, Instagram and LinkedIn access depends on the configured route and its
authorization. Catalog entries are not proof of implemented or working access.
Paid providers and browser-cookie access require explicit authorization.

Check the platform's current documentation when diagnosing transport failures.
Use only one bounded alternate route and record the actual source status;
a local readiness check alone cannot establish live availability.
