# ADR-0002: Discovery-first product positioning

- **Status**: Accepted
- **Date**: 2026-09-26
- **Supersedes**: ADR-0001's GTM-only product positioning; preserves its evidence, validation, and host-neutral architecture decisions.

## Context

The original GTM framing over-emphasized the final decision brief. The user clarified the broader starting problem: product managers, GTM practitioners, and technology workers spend time monitoring fragmented recent discussions and still miss new tools, needs, user complaints, and changes across sources. The differentiator is evidence quality and the option to continue toward product or GTM judgment.

## Decision

Keep one Skill and the existing seven research modes. Make evidence-linked recent information and demand discovery the primary use case. Answers should first distinguish new developments, repeated patterns, isolated observations, and source gaps. Provide product/GTM implications and recommendations when the user asks for judgment or action, not merely because the pipeline can generate them. The recent window is a useful default, not a promise that every topic has enough recent evidence.

## Why

This serves the information-discovery workflow through dated findings and reusable evidence. It avoids reducing all research questions to GTM advice and preserves the existing evidence-ledger and FACT/INFERENCE safeguards.

## Trade-offs

The default engine path still foregrounds recommendations for compatibility. The Skill must choose `--discovery-only` for information-seeking questions; that path skips recommendation generation and uses a discovery brief title. Host routing and the quality of actual discovery findings still require real-question evaluation.

## Alternatives Rejected

Keep a GTM-decision-only trigger: too narrow for demand and technology discovery. Use only a broad social-search summary: would lose the evidence and judgment distinction. Split discovery and decision support into separate Skills now: duplicates the shared research pipeline without evidence of a workflow split.

## Consequences

Product language and Skill discovery now include recent tools, needs, and real user discussions. Offline integration verifies that an information-only run avoids an unrequested action. Acceptance must still test an information-only question separately from a decision question on live sources. Source coverage and recency need honest qualification.
