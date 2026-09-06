# Official Web Classifier — Phase 4 Source

| Attribute       | Value                                                |
|-----------------|------------------------------------------------------|
| Support status  | **SUPPORTED** (deterministic matcher)                |
| Pure function   | YES (no network, no I/O)                             |
| Auth required   | No                                                   |
| Env vars        | (none)                                               |
| Default config  | `config/official_domains.yaml`                       |
| Live tests      | (none — matcher is offline by construction)          |

## Architecture

```
URL (any source's RawSourceResult.url)
  ↓
OfficialDomainMatcher
  ├── exact host match
  ├── subdomain (label-aligned) match
  ├── GitHub owner match (github.com/<owner>/<repo>)
  └── (no-op fallback)
  ↓
OfficialClassification
  is_official: bool
  owner: str | None
  matched_kind: "domain" | "github"
  matched_value: str | None
  ↓
RawSourceResult.raw_metadata ({"official": True, "official_owner": ...})
  ↓
Phase 3 normalizer
  → if official: source_tier = 1, evidence_quality = 1.0
```

## Behaviour

* Matching is **strict / label-aligned**: `company.com.evil.org` is
  NEVER considered a match for `company.com`, and `evilcompany.com`
  is NEVER a match either.
* Subdomains are accepted (`docs.company.com`, `www.company.com`).
* Case is normalized: `COMPANY.COM` matches `company.com`.
* `:port` is stripped before matching: `company.com:8080` matches
  `company.com`.
* `www.` prefix is stripped: `www.company.com` matches `company.com`.

## Verification

* Every URL classified as official is recorded in
  `raw_metadata.official=true` PLUS `raw_metadata.official_owner=<entity>`.
* The Phase 3 normalizer reads this metadata and promotes the
  resulting evidence to `source_tier=1` / `evidence_quality=1.0`,
  even when the underlying adapter source is unknown to `_TIER_MAP`
  — the official flag IS the verification.

## Known limitations

* Only the entities listed in `config/official_domains.yaml` are
  classified as first-party. Adding a new verified domain is a
  one-line PR.
* The matcher is deliberately not fuzzy — it intentionally rejects
  lookalikes. Adding an "approximate" fallback would re-introduce
  the spoof risk the strict matcher was built to avoid.
* Phase 4 ships this classifier as a functional primitive; the
  higher-level "filter all results through the classifier before they
  reach the normalizer" wiring is left to each adapter's caller.
