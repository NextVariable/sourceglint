# Reddit — Phase 4 Source

| Attribute       | Value                                                |
|-----------------|------------------------------------------------------|
| Support status  | **AUTH_REQUIRED** (contract-complete, disabled by default) |
| Source class    | `reddit` / community / T2                            |
| Auth required   | **Yes** (`REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET`) |
| Env vars        | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`           |
| Default limit   | 20 results per query (PRD §16)                       |
| Cache TTL       | 900 s (config/sources.yaml)                          |
| Live tests      | `RUN_LIVE_TESTS=1 GITHUB_TOKEN=… pytest tests/live -q -k reddit` (skipped if no creds) |

## Architecture

We use the LEGITIMATE Reddit OAuth2 client_credentials flow against
official endpoints. We do NOT scrape HTML, do NOT extract cookies, do
NOT reverse-engineer private endpoints, do NOT store user credentials.

* **Token endpoint**: `https://www.reddit.com/api/v1/access_token`
* **Search endpoint**: `https://oauth.reddit.com/search`
* Method: OAuth2 client_credentials grant with HTTP Basic
  Authentication (`Authorization: Basic base64(client_id:client_secret)`)
* Token cache: in-memory only (no disk, no Evidence field, no logs).
* Clock: comes from injected `now_provider` (deterministic-engine
  invariant: no `time.time()` in `src/`).

```
RedditAdapter
   ↓
   ├── token endpoint (Basic auth, cached)
   └── search endpoint (Bearer auth)
           ↓
       RawSourceResult list
```

## Auth boundary

* `client_id` / `client_secret` are **constructor-injected only**
  (no environment reads inside this module). Hosts are expected to
  wire the values themselves.
* When EITHER credential is missing or empty, the adapter raises
  `AdapterAuthMissing` BEFORE issuing any HTTP request. The orchestrator
  records `AUTO_MISSING` and continues with the other sources.
* Tokens are cached in-memory only; never logged, never echoed in
  error reprs.
* The token endpoint itself returns 401/403 → `AdapterAuthMissing`.

## Behaviour

* `source_native_id = name` (`t3_…`); stable for deduplication.
* When the item lacks an external URL, the canonical permalink is
  used (e.g. `https://www.reddit.com/r/<sub>/comments/<id>/`).
* Score is recorded as `engagement.upvotes` (never as
  `evidence_quality` — Phase 4 §9 forbids confusing popularity with
  evidence weight).
* Comment count is recorded as `engagement.comments`.
* Deleted content (`[deleted]` / `[removed]`) is silently dropped.
* `created_utc` is converted to RFC3339 UTC; missing/invalid → omit.

## Failure mapping

| Source                       | Phase 3 SourceStatus  |
|------------------------------|-----------------------|
| Missing creds                | AUTH_MISSING (no HTTP) |
| 200 + valid JSON             | SUCCESS               |
| HTTP 429 (either endpoint)   | RATE_LIMITED          |
| HTTP 401/403 (either)        | AUTH_MISSING          |
| HTTP 5xx                     | UNAVAILABLE           |
| HTTP timeout                 | TIMEOUT               |
| HTTP 4xx (other)             | INVALID_RESPONSE      |
| Malformed JSON               | INVALID_RESPONSE      |
| Missing required field       | INVALID_RESPONSE      |
| Deleted content              | (silently dropped)    |

## Explicitly NOT implemented (PRD §9 forbidden list)

These are deliberately NOT in the adapter, ever:

* Cookie / session extraction
* Browser-session stealing
* Login automation
* CAPTCHA bypass
* User credential storage
* Undocumented anti-bot circumvention
* Rotating proxies
* HTML scraping of `reddit.com`
* Reverse-engineering of private endpoints

## Known limitations

* Phase 4 ships the OAuth2 client_credentials flow only — fine for
  search-only access. If Reddit changes OAuth policies, the adapter
  is expected to fall back to `AdapterAuthMissing` rather than
  falling back to scraping.
* Comment listings and `r/<sub>/comments` JSON endpoints are NOT
  exercised; this is MVP scope per PRD §15.
* Token caching is per-process (no cross-run caching). The 1-hour
  default TTL keeps the network footprint minimal.

## How to enable

```python
from sourceglint.connectors.reddit import RedditAdapter

adapter = RedditAdapter(
    client_id="…",       # from REDDIT_CLIENT_ID
    client_secret="…",   # from REDDIT_CLIENT_SECRET
)
# pass into your adapter_factory inside PipelineConfig runtime
```

If `client_id`/`client_secret` are absent at runtime, the adapter
raises `AdapterAuthMissing` cleanly — the pipeline keeps running and
records the source's status as `auth_missing`.
