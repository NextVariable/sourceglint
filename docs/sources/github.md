# GitHub — Phase 4 Source

| Attribute       | Value                                                |
|-----------------|------------------------------------------------------|
| Support status  | **SUPPORTED** (real official API adapter)            |
| Source class    | `github` / official / T1                             |
| Auth required   | No (anonymous works; token optional)                 |
| Env vars        | `GITHUB_TOKEN` (optional)                            |
| Default limit   | 20 results per query (PRD §16)                       |
| Cache TTL       | 3600 s (config/sources.yaml)                         |
| Live tests      | `RUN_LIVE_TESTS=1 pytest tests/live -q -k github`     |

## Architecture

* **Search endpoint**: `https://api.github.com/search/repositories`
* **No HTML scraping**; we speak GitHub's REST search API.
* Source-of-truth release-type signal: `created_at` is the canonical
  published date (NOT `updated_at`); this preserves GTM's "launch
  moment" interpretation per PRD §8.

```
GitHubAdapter
  ↓
StdlibHttpClient (retry: 403/429/5xx/timeout; no retry on 4xx)
  ↓
api.github.com/search/repositories
  ↓
RawSourceResult list
```

## Auth boundary

* Public anonymous path works at 60 req/h.
* Token lifted path works at 5000 req/h.
* Token is **constructor-injected only** (no environment reads inside
  this module). The host integration layer decides how to source it
  from `GITHUB_TOKEN`.
* Token never appears in error reprs; verified by tests.
* Empty-string token behaves like anonymous (no Authorization header).

## Behaviour

* `source_native_id = full_name` ("acme/awesome") — stable across re-runs.
* Items missing `created_at` are dropped (Closeout §3: unknown ≠ neutral).
* `stargazers_count` → engagement.upvotes (raw integer, never smoothed).
* `forks_count` → engagement.comments.
* `owner.login` → evidence.author.
* `raw_metadata` keeps `github_full_name`, `github_repo_id`,
  `github_pushed_at`, `github_updated_at`, `github_language` for
  downstream consumers.
* **Verified owners** are flagged via the official-domain classifier:
  when the URL refers to a known owner, `raw_metadata.official=true`
  is set and the normalizer promotes the evidence to T1 (Phase 4 §20).

## Failure mapping

| Source                 | Phase 3 SourceStatus  |
|------------------------|-----------------------|
| 200 + JSON             | SUCCESS               |
| HTTP 429 / 403         | RATE_LIMITED (GitHub uses 403 for abuse-detection) |
| HTTP 5xx               | UNAVAILABLE           |
| HTTP 401 (with token)  | AUTH_MISSING          |
| HTTP timeout           | TIMEOUT               |
| HTTP 4xx (other)       | INVALID_RESPONSE      |
| Malformed JSON         | INVALID_RESPONSE      |
| Missing top-level items| INVALID_RESPONSE      |
| Missing full_name/id   | INVALID_RESPONSE      |

## Known limitations

* The MVP scope is `search/repositories` only. `releases` capability
  is listed in `config/sources.yaml` but is **not** implemented in
  this Phase 4 commit (PRD §8 explicitly allows deferral).
* `updated_at` is recorded as raw metadata only — promoted to
  "evidence published_at" only when `created_at` is missing.
* Anonymous rate limit is 60 req/h, easily exhausted; the
  PipelineConfig caches results so an ordinary run rarely hits the
  ceiling.
