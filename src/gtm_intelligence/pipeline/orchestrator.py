"""ResearchPipeline orchestrator (Phase 3 §23).

Sequential pipeline:

  validate plan + registry
  -> expand queries
  -> build retrieval plans
  -> select eligible sources
  -> for each (source, query): retrieve via adapter (with optional cache)
  -> normalize raw results to Evidence
  -> apply time window filter
  -> deduplicate
  -> write to ledger
  -> build coverage report

The orchestrator owns:
  * composition (calls into the modules)
  * error capture (per-source degradation)
  * ledger write ordering

The orchestrator MUST NOT:
  * call LLM
  * score signals
  * synthesize insights
  * generate recommendations
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

import jsonschema
from rfc3339_validator import validate_rfc3339

from ..errors import ConfigValidationError
from ..ledger import EvidenceLedger
from ..normalization import (
    EvidenceNormalizationError,
    normalize_raw,
    validate_evidence_payload,
)
from .adapters import AdapterError, FakeSourceAdapter, RawSourceResult, SourceAdapter
from .cache import RetrievalCache, cache_key_for
from .coverage import CoverageReport, build_coverage_report
from .deduplication import deduplicate
from .degradation import (
    AllSourcesFailedError,
    InvalidResearchPlanError,
    SourceStatus,
    SourceStatusReport,
    build_status_report,
    classify_adapter_exception,
)
from .query_expansion import expand_queries
from .retrieval_plan import build_retrieval_plans
from .source_registry import eligible_sources_for, load_registry
from .time_filter import apply_time_filter, TimeWindowError


@dataclass(frozen=True)
class PipelineConfig:
    """Pipeline-wide configuration. as_of is injected (deterministic).

    Cache TTL ownership (Closeout §4):
      1. per-request override via `cache_ttl_seconds` on PipelineConfig
         (set by the orchestrator to the registry entry's `cache_ttl`)
      2. `default_cache_ttl_seconds` (Phase 3 default = 900 s)

    Phase 3 wires rule (1) from the SourceEntry cache_ttl that the
    registry runtime already loads. Phase 4 may add a per-request
    override hook on the orchestrator.run(...) signature without
    touching this config schema.
    """

    as_of: str
    window: str = "current"
    cache: RetrievalCache | None = None
    default_cache_ttl_seconds: int = 900
    cache_ttl_seconds: int | None = None  # explicit per-request override

    def __post_init__(self):
        # __setattr__ is frozen — go around via object.__setattr__.
        if self.default_cache_ttl_seconds < 0:
            raise ValueError(
                f"default_cache_ttl_seconds must be >= 0; got {self.default_cache_ttl_seconds}"
            )
        if self.cache_ttl_seconds is not None and self.cache_ttl_seconds < 0:
            raise ValueError(
                f"cache_ttl_seconds must be >= 0 or None; got {self.cache_ttl_seconds}"
            )


@dataclass(frozen=True)
class ResearchPipelineResult:
    """Structured output of one pipeline run."""

    evidence_ids: list[str]
    coverage: CoverageReport
    warnings: list[str]
    source_statuses: dict[str, SourceStatusReport]


# Adapter factory type: name -> adapter instance (or None to skip).
AdapterFactory = Callable[[str, Mapping[str, object]], SourceAdapter | None]


def _validate_plan_shape(plan: Mapping[str, object]) -> None:
    """Catch the most common Research-Plan shape errors BEFORE retrieval."""
    if not isinstance(plan, Mapping):
        raise InvalidResearchPlanError("plan must be a mapping")
    if not str(plan.get("topic") or "").strip():
        raise InvalidResearchPlanError("plan.topic is required and non-empty")
    mode = str(plan.get("mode") or "")
    if mode not in {"general", "trend", "competitor", "market", "voc", "launch", "channel"}:
        raise InvalidResearchPlanError(f"plan.mode unknown: {mode!r}")
    if not plan.get("time_window"):
        raise InvalidResearchPlanError("plan.time_window is required")


def _validate_registry_shape(sources: Iterable[Mapping[str, object]]) -> None:
    """Schema-validate sources before retrieval to surface registry errors."""
    # Phase 3 simplification: we use the load_registry validator by feeding
    # the sources through a temp yaml loader.
    import yaml
    payload = list(sources)
    if not payload:
        return
    try:
        # Reuse load_registry — it validates via the schema.
        load_registry(yaml_text=yaml.safe_dump(payload, allow_unicode=True, sort_keys=True))
    except ConfigValidationError as exc:
        raise ConfigValidationError(str(exc))


class ResearchPipeline:
    """Sequential orchestrator. Single responsibility: compose the modules."""

    def __init__(
        self,
        *,
        config: PipelineConfig,
        adapter_factory: AdapterFactory,
    ) -> None:
        self.config = config
        self.adapter_factory = adapter_factory

    def run(
        self,
        *,
        plan: Mapping[str, object],
        sources: Sequence[Mapping[str, object]],
        ledger: EvidenceLedger,
    ) -> ResearchPipelineResult:
        # 1) Validate plan + registry before any I/O.
        _validate_plan_shape(plan)
        _validate_registry_shape(sources)

        # 2) Expand queries.
        expanded = expand_queries(plan)

        # 3) Filter eligible sources via the registry runtime.
        # Build a SourceRegistry from the passed-in sources so we honor
        # the test/runtime registry, not config/sources.yaml.
        import yaml as _yaml
        from .source_registry import _coerce_entry as _ce
        try:
            reg_yaml = _yaml.safe_dump(list(sources), allow_unicode=True, sort_keys=True)
            registry = load_registry(yaml_text=reg_yaml)
            # Build a name -> SourceEntry map for cache_ttl lookups (Closeout §4).
            source_entries_by_name = {
                e["name"]: _ce(e) for e in (sources or [])
            }
        except ConfigValidationError:
            raise
        eligible = eligible_sources_for(
            registry,
            plan_market=str(plan.get("market") or "global"),
            query_language=str(plan.get("languages") or ["en"])[0]
            if isinstance(plan.get("languages"), list) and plan.get("languages")
            else "en",
        )

        # 4) Build retrieval plans.
        retrievals = build_retrieval_plans(plan, list(sources), expanded)

        # 5) Execute retrievals per source, capturing status.
        raw_results: list[RawSourceResult] = []
        per_source: dict[str, SourceStatusReport] = {}
        warnings: list[str] = []

        # Group retrieval plans by source so each adapter call is one request
        # (the cache key includes the query, so a per-(source,query) request
        # is also acceptable; we group for symmetry with Phase 4).
        by_source: dict[str, list] = {}
        for r in retrievals:
            by_source.setdefault(r.source, []).append(r)

        for source_name in sorted(by_source.keys()):
            rep = SourceStatusReport(source=source_name)
            adapter = self.adapter_factory(source_name, plan)
            if adapter is None:
                rep.status = SourceStatus.UNAVAILABLE
                rep.append_warning("no adapter registered for source")
                per_source[source_name] = rep
                continue
            adapter_results: list[RawSourceResult] = []
            for r in by_source[source_name]:
                # Cache check first.
                cached = self._cache_get(source_name, r, plan)
                if cached is not None:
                    adapter_results.extend(cached)
                    continue
                request = {
                    "query": r.query,
                    "query_language": r.query_language,
                    "market": r.market,
                    "retrieved_at": self.config.as_of,
                }
                try:
                    out = adapter.retrieve(plan=plan, request=request)
                except AdapterError as exc:
                    status = classify_adapter_exception(exc)
                    rep.status = status
                    rep.append_warning(f"{status.value}: {exc.reason}")
                    break
                except Exception as exc:  # pragma: no cover - defensive
                    rep.status = SourceStatus.UNAVAILABLE
                    rep.append_warning(f"unavailable: {exc}")
                    break
                # Cache write.
                ttl = self._ttl_for_source(
                    source_name, source_entries_by_name
                )
                self._cache_put(
                    source_name,
                    r,
                    plan,
                    [_rr.to_dict() for _rr in out],
                    ttl_seconds=ttl,
                )
                adapter_results.extend(out)

            raw_results.extend(adapter_results)
            rep.count = len(adapter_results)
            if rep.status == SourceStatus.SUCCESS and rep.warnings:
                rep.status = SourceStatus.PARTIAL
            per_source[source_name] = rep

        # 6) Normalize raw -> Evidence.
        evidence_list: list[dict] = []
        normalization_warnings = 0
        for raw in raw_results:
            try:
                ev = normalize_raw(
                    raw,
                    as_of=self.config.as_of,
                    window=self.config.window,
                )
                validate_evidence_payload(ev)
            except (EvidenceNormalizationError, jsonschema.ValidationError) as exc:
                normalization_warnings += 1
                warnings.append(f"normalization_dropped: {raw.source}/{raw.source_native_id}: {exc}")
                continue
            evidence_list.append(ev)
        if normalization_warnings:
            warnings.append(f"normalization_dropped={normalization_warnings}")

        # 7) Time filter.
        tf = apply_time_filter(
            evidence_list,
            plan.get("time_window") or {},
            as_of=self.config.as_of,
        )
        evidence_list = tf.kept
        if tf.dropped:
            warnings.append(f"time_filter_dropped={len(tf.dropped)}")

        # 8) Deduplicate.
        dedup = deduplicate(evidence_list)
        evidence_list = dedup.kept
        if dedup.duplicate_count:
            warnings.append(f"dedup_dropped={dedup.duplicate_count}")

        # 9) Write ledger.
        written: list[str] = []
        for ev in evidence_list:
            try:
                rec = ledger.add(ev)
                written.append(rec.evidence_id)
            except Exception as exc:
                warnings.append(f"ledger_reject: {ev.get('evidence_id', '<')}: {exc}")

        # 10) Coverage report.
        coverage = build_coverage_report(
            requested_sources=list({r.source for r in retrievals}),
            attempted_sources=sorted(by_source.keys()),
            source_statuses=per_source,
            expanded_queries=[
                q.to_dict() if hasattr(q, "to_dict")
                else {
                    "text": getattr(q, "text", ""),
                    "intent": getattr(q, "intent", ""),
                    "query_language": getattr(q, "query_language", ""),
                    "market": getattr(q, "market", ""),
                }
                for q in expanded
            ],
            raw_results=[rr.to_dict() for rr in raw_results],
            normalized_evidence=evidence_list,
            deduplicated_dropped=dedup.duplicate_count,
            dropped_by_time_filter=len(tf.dropped),
        )

        # 11) All-sources-failed guard.
        if (
            coverage.attempted_sources
            and not coverage.successful_sources
            and coverage.attempted_sources == coverage.failed_sources
        ):
            raise AllSourcesFailedError(per_source=per_source)

        return ResearchPipelineResult(
            evidence_ids=written,
            coverage=coverage,
            warnings=warnings,
            source_statuses=per_source,
        )

    def _cache_get(
        self,
        source: str,
        retrieval,
        plan: Mapping[str, object],
    ) -> list[RawSourceResult] | None:
        if self.config.cache is None:
            return None
        key = cache_key_for(
            source=source,
            query=retrieval.query,
            query_language=retrieval.query_language,
            market=retrieval.market,
            time_window=retrieval.time_window,
        )
        cached = self.config.cache.get(key, as_of=self.config.as_of)
        if cached is None:
            return None
        out: list[RawSourceResult] = []
        for entry in cached:
            if not isinstance(entry, dict):
                continue
            try:
                out.append(RawSourceResult(**entry))
            except TypeError:
                # Cached value doesn't match the current RawSourceResult shape —
                # treat as miss.
                return None
        return out

    def _ttl_for_source(
        self,
        source_name: str,
        source_entries_by_name: Mapping[str, object],
    ) -> int:
        """Resolve cache TTL for one source.

        Priority (Closeout §4):
          1. explicit per-request override on PipelineConfig.cache_ttl_seconds
          2. source-specific cache_ttl from the registry entry
             (cache_ttl == 0 is treated as "do not cache", returns 0)
          3. PipelineConfig.default_cache_ttl_seconds (900)
        """
        cfg_ttl = self.config.cache_ttl_seconds
        if cfg_ttl is not None:
            return cfg_ttl
        entry = source_entries_by_name.get(source_name)
        if entry is None:
            return self.config.default_cache_ttl_seconds
        entry_ttl = getattr(entry, "cache_ttl", None)
        if entry_ttl is None:
            return self.config.default_cache_ttl_seconds
        if entry_ttl <= 0:
            return 0
        return entry_ttl

    def _cache_put(
        self,
        source: str,
        retrieval,
        plan: Mapping[str, object],
        items: list[dict],
        *,
        ttl_seconds: int,
    ) -> None:
        """Write raw-result items to the cache at the resolved TTL.

        ttl_seconds <= 0 means "do not cache". A cache failure NEVER
        breaks the pipeline (Closeout §17: cache must not be required
        for correctness).
        """
        if self.config.cache is None:
            return
        if ttl_seconds <= 0:
            return
        key = cache_key_for(
            source=source,
            query=retrieval.query,
            query_language=retrieval.query_language,
            market=retrieval.market,
            time_window=retrieval.time_window,
        )
        try:
            self.config.cache.set(
                key,
                items,
                ttl_seconds=ttl_seconds,
                as_of=self.config.as_of,
            )
        except Exception:  # pragma: no cover - cache failure must not break pipeline
            pass