# ADR-0003: Recent research is the default output

- **Status**: Accepted
- **Date**: 2026-09-26
- **Supersedes**: ADR-0002's compatibility default for recommendations. The evidence and reasoning contracts from ADR-0001 remain in force.

## Context

The first discovery-first change still required `--discovery-only`, so a bare topic continued to produce a GTM decision brief. That inverted the user's actual task. A user entering a topic such as “AI Video” wants a dated, deduplicated account of what has appeared and what people are discussing, not an unsolicited action plan.

## Decision

The public API and CLI default to recent information research without GTM implication or recommendation generation. An explicit `decision_support` API option or `--decision-support` CLI flag adds those stages. Keep one Skill and the current evidence, signal, FACT, and INFERENCE pipeline. If retrieval succeeds but no signal is validated, the discovery brief still lists a bounded set of dated source items without promoting them to a trend. The Skill entrypoint states the actual available sources and must not imply direct X or TikTok coverage. YouTube direct metadata coverage was added later and is reported with its local-tool boundary.

## Why

The core job is reducing information fragmentation and recency confusion. Research should be useful to a product manager, creator, or technology worker without requiring a GTM question. Optional decision support preserves the existing deeper capability.

## Trade-offs

The package name still says GTM and the underlying report structure still comes from the older intelligence engine. Platform breadth, trend-over-time validation, and real-world discovery quality are not solved by changing the default. Explicit decision callers must now opt in.

## Alternatives Rejected

Keep `--discovery-only` as an opt-in: a bare-topic invocation remains wrong. Split into two Skills: unnecessary duplication before the research path is validated.

## Consequences

Acceptance must separately test a bare topic and an explicit decision question. A successful pipeline status cannot be read as proof of cross-platform coverage or that a topic is truly rising.
