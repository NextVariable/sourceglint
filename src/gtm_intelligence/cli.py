"""Phase 7 §22–§24, §53–§55 — minimal host-neutral CLI.

    gtm-intelligence "recent Japan AI meeting assistant market changes" \\
        [--mode market] [--market jp] [--window 30] [--language en] \\
        [--model FILE_OR_MODULE] [--registry sources.yaml] \\
        [--as-of 2026-09-09T00:00:00Z] [--output brief.md] [--json] [--debug]

Contract:
  * stdout  -> artifact (Markdown brief by default, JSON with --json)
  * stderr  -> warnings / errors (credential-NAME-only, §25 / §55)
  * exit 0  -> SUCCESS / PARTIAL / NO_EVIDENCE (usable result)
  * exit 1  -> invalid request (bad args, clarification required)
  * exit 2  -> pipeline failed / no usable result (or argparse usage error)

Security (§50): the CLI never uses eval/exec/shell; the query is always
passed as data to the canonical ``run_gtm_intelligence`` Python API.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .application.api import run_gtm_intelligence
from .application.runtime import default_adapter_factory
from .host_stdio import StdioHostSource
from .interface.request import MODES

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_PIPELINE_FAILED = 2

_MODEL_HELP = (
    "Model injection for offline runs: a .py file exporting build_model() "
    "(no network), or 'module:attribute'. Without a model the semantic "
    "stages cannot run — the core bundles no vendor LLM client."
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gtm-intelligence",
        description=(
            "Evidence-linked recent information and demand discovery, with "
            "optional product and GTM decision support."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("query", help="What to research (natural language).")
    p.add_argument("--mode", choices=MODES, default="", help="Engine mode override.")
    p.add_argument("--market", default="", help="Market override (iso code or name).")
    p.add_argument("--window", type=int, default=None, metavar="DAYS",
                   help="Relative window in days (default parse / 30).")
    p.add_argument("--language", action="append", default=[], dest="languages",
                   help="Research language (repeatable).")
    p.add_argument("--entity", action="append", default=[], dest="entities",
                   help="Named entity (product/company). Repeatable.")
    p.add_argument("--target", default="", help="Primary entity of interest.")
    p.add_argument("--baseline", action="store_true",
                   help="Include prior-window baseline evidence.")
    p.add_argument("--discovery-only", action="store_true",
                   help="Research recent findings without generating recommendations.")
    p.add_argument("--model", default=None, metavar="FILE|MOD:ATTR", help=_MODEL_HELP)
    p.add_argument("--host-sources-stdio", action="store_true",
                   help="Ask the host agent to handle host_web_search and official_web via JSON lines.")
    p.add_argument("--registry", default=None, metavar="YAML",
                   help="source registry YAML (default config/sources.yaml).")
    p.add_argument("--as-of", default=None, metavar="ISO",
                   help="Deterministic 'as of' timestamp (ISO 8601).")
    p.add_argument("--output", default=None, metavar="FILE",
                   help="Write the brief markdown to FILE (stdout otherwise).")
    p.add_argument("--json", action="store_true", help="Emit SkillResult JSON.")
    p.add_argument("--debug", action="store_true",
                   help="Print stage statuses + warnings to stderr.")
    return p


def _load_registry(path: str | None) -> list[dict[str, Any]] | None:
    """Registry payload from --registry, or None => api default."""
    if not path:
        return None
    import yaml

    p = Path(path)
    if not p.exists():
        raise ValueError(f"--registry file not found: {path}")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"--registry must contain a list of source entries: {path}")
    return data


def _load_model(spec: str | None) -> Any:
    """Resolve the injected model from a .py file or 'module:attribute'.

    File form: the file must define ``build_model()`` returning a model
    instance. Module form: ``package.module:attribute``.
    """
    if not spec:
        return None
    if ":" in spec and not spec.endswith(".py"):
        module_name, _, attr = spec.partition(":")
        import importlib

        module = importlib.import_module(module_name)
        factory = getattr(module, attr)
        if callable(factory):
            return factory()
        return factory
    path = Path(spec)
    if not path.exists() or path.suffix != ".py":
        raise ValueError(
            f"--model must be a .py file defining build_model() or "
            f"'module:attribute'; got {spec!r}"
        )
    module_name = f"_gtm_cli_model_{abs(hash(str(path.resolve()))) % (10 ** 8)}"
    spec_obj = importlib.util.spec_from_file_location(module_name, str(path.resolve()))
    if spec_obj is None or spec_obj.loader is None:
        raise ValueError(f"cannot load model file: {path}")
    module = importlib.util.module_from_spec(spec_obj)
    spec_obj.loader.exec_module(module)
    factory = getattr(module, "build_model", None)
    if not callable(factory):
        raise ValueError(f"model file must define build_model(): {path}")
    return factory()


def _emit(result: Any, args: argparse.Namespace, stream: Any) -> None:
    """Write the artifact to stdout or --output; warnings to stderr."""
    if args.output:
        Path(args.output).write_text(result.brief_markdown, encoding="utf-8")
        print(f"brief written to {args.output}", file=sys.stderr)
    elif args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.brief_markdown)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        sources = _load_registry(args.registry)
        model = _load_model(args.model)
        adapter_factory = None
        if args.host_sources_stdio:
            def adapter_factory(name, plan):
                if name in ("host_web_search", "official_web"):
                    return StdioHostSource(name)
                return default_adapter_factory(name, plan)
        result = run_gtm_intelligence(
            args.query,
            mode=args.mode,
            market=args.market,
            window_days=args.window,
            languages=tuple(args.languages),
            entities=tuple(args.entities),
            target=args.target,
            baseline=args.baseline,
            discovery_only=args.discovery_only,
            model=model,
            adapter_factory=adapter_factory,
            sources=sources,
            as_of=args.as_of or datetime.now(timezone.utc),
        )
    except ValueError as exc:
        # Invalid request / bad model spec — user fixable.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INVALID
    except Exception as exc:  # pragma: no cover - defensive terminal failure
        print(f"pipeline error: {exc}", file=sys.stderr)
        if args.debug:
            import traceback

            traceback.print_exc(file=sys.stderr)
        return EXIT_PIPELINE_FAILED

    if args.debug:
        print("stage statuses:", dict(result.stage_statuses), file=sys.stderr)
        for w in result.warnings:
            print(f"warning: {w}", file=sys.stderr)

    if result.request is not None and result.request.needs_clarification:
        print(
            f"clarification required: {result.warnings[0] if result.warnings else ''}",
            file=sys.stderr,
        )
        return EXIT_INVALID

    if result.status.value == "FAILED":
        print("no usable result.", file=sys.stderr)
        for w in result.warnings:
            print(f"warning: {w}", file=sys.stderr)
        return EXIT_PIPELINE_FAILED

    if result.status.value == "NO_EVIDENCE":
        print(
            "note: no usable evidence was retrieved for this research request.",
            file=sys.stderr,
        )

    _emit(result, args, sys.stdout)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
