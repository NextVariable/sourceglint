# ADR-0002: Discovery-first product positioning

- **Status**: Accepted
- **Date**: 2026-09-26
- **Supersedes**: ADR-0001's GTM-only product positioning; preserves its evidence, validation, and host-neutral architecture decisions.

## Context


## Decision

Keep one Skill and the existing seven research modes. Make evidence-linked recent information and demand discovery the primary use case. Answers should first distinguish new developments, repeated patterns, isolated observations, and source gaps. Provide product/GTM implications and recommendations when the user asks for judgment or action, not merely because the pipeline can generate them. The recent window is a useful default, not a promise that every topic has enough recent evidence.

## Why


## Trade-offs

The default engine path still foregrounds recommendations for compatibility. The Skill must choose `--discovery-only` for information-seeking questions; that path skips recommendation generation and uses a discovery brief title. Host routing and the quality of actual discovery findings still require real-question evaluation.

## Alternatives Rejected


## Consequences

Product language and Skill discovery now include recent tools, needs, and real user discussions. Offline integration verifies that an information-only run avoids an unrequested action. Acceptance must still test an information-only question separately from a decision question on live sources. Source coverage and recency need honest qualification.
