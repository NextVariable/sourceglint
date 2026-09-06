# Host Web Search — Phase 4 Source

| Attribute       | Value                                                |
|-----------------|------------------------------------------------------|
| Support status  | **HOST_CAPABILITY**                                  |
| Source class    | `host_web_search` / web / T4 secondary               |
| Auth required   | No                                                   |
| Env vars        | (none directly; the injected capability owns them)   |
| Default limit   | 20 hits per query (PRD §16, configurable per-source) |
| Cache TTL       | 900 s (config/sources.yaml)                          |
| Live tests      | `RUN_LIVE_TESTS=1 pytest tests/live -q` (only when the host integration layer is wired) |
| Spec           | PRD §4–§5                                            |

## Architecture

```
Host / Harness
    ↓
SearchCapability      ← neutral Protocol (this repo defines the interface only)
    ↓
HostWebSearchAdapter  ← maps capability → SourceAdapter
    ↓
RawSourceResult       ← Phase 3 DTO
```

The CORE repository does not import any vendor SDK. Concrete
implementations of `SearchCapability` (WorkBuddy search tool, Claude
WebSearch, Tavily, Exa, your custom backend, …) live in the host
integration layer and are passed in by the host at runtime.

## Behaviour

* Empty result → success with `[]` (NOT failure).
* Capability missing (`None`) → `AdapterUnavailable`.
* Capability raises `SearchCapabilityTimeout` → `AdapterTimeout`.
* Capability raises any other exception → `AdapterUnavailable`.
* Capability returns malformed payload or non-`WebSearchHit` items →
  `AdapterInvalidResponse` with the offending index in the reason.
* Hit missing URL or title → `AdapterInvalidResponse` (silently
  dropping would hide a host contract violation).
* `limit` is clamped to `max_per_query` (defaults to 20).

## Failure mapping

| Source                      | Phase 3 SourceStatus  |
|-----------------------------|-----------------------|
| Capability returns `[]`     | SUCCESS               |
| `AdapterUnavailable`        | UNAVAILABLE           |
| `AdapterTimeout`            | TIMEOUT               |
| `AdapterInvalidResponse`    | INVALID_RESPONSE      |
| HTTP 429                    | (capability concern)  |

## Known limitations

* The CORE repository ships zero vendor bindings. Test the
  `HostWebSearchAdapter` end-to-end only after the host integration
  layer wires a `SearchCapability` instance.
* No pagination; `limit` is a hard cap and clamping is documented.
* The capability contract is `query → list[WebSearchHit]`; richer
  pagination semantics are deferred to a future phase.
