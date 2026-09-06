# Hacker News — Phase 4 Source

| Attribute       | Value                                                |
|-----------------|------------------------------------------------------|
| Support status  | **SUPPORTED** (real API adapter)                     |
| Source class    | `hacker_news` / community / T2                       |
| Auth required   | No (public Algolia + Firebase JSON)                  |
| Env vars        | (none)                                               |
| Default limit   | 20 hits per query (PRD §16)                          |
| Cache TTL       | 1800 s (config/sources.yaml)                         |
| Live tests      | `RUN_LIVE_TESTS=1 pytest tests/live -q -k hacker_news` |

## Architecture

* **Search endpoint**: `https://hn.algolia.com/api/v1/search`
* **Item URL prefix**: `https://news.ycombinator.com/item?id=`
* **No HTML scraping**: we speak JSON only.

```
HackerNewsAdapter
  ↓
StdlibHttpClient (with retry on 429/5xx, no retry on 4xx)
  ↓
HN Algolia search API
  ↓
RawSourceResult list
```

## Behaviour

* Story without external URL (Ask HN): the stable HN item URL
  (`news.ycombinator.com/item?id=<objectID>`) is used as `url`.
* Deleted/dead items are silently dropped.
* `created_at_i` is converted to RFC3339 UTC; missing/non-int → empty
  (Closeout §3: omit, do not invent).
* Engagement is a `{points: int, comments: int}` mapping.
* `source_native_id = objectID` is the stable key for deduplication.

## Failure mapping

| Source                 | Phase 3 SourceStatus  |
|------------------------|-----------------------|
| Success                | SUCCESS               |
| HTTP 429               | RATE_LIMITED          |
| Other 5xx / transient  | UNAVAILABLE           |
| HTTP timeout           | TIMEOUT               |
| HTTP 4xx (non-429)     | INVALID_RESPONSE      |
| Malformed JSON         | INVALID_RESPONSE      |
| Missing top-level hits | INVALID_RESPONSE      |
| Hit missing objectID   | INVALID_RESPONSE      |

## Known limitations

* Search ranking follows Algolia's relevance; we do not post-process.
* Comments are not retrieved (Phase 4 MVP scope).
* The free Algolia API path enforces a 60 req/min ceiling; the cache
  TTL of 1800 s absorbs ordinary run cadences. Heavy automated runs
  may be rate-limited briefly — the adapter surfaces this as
  `rate_limited` and the pipeline continues with other sources.
* Time field returned by Algolia is unix seconds; timezone is implicit
  UTC.
