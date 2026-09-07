# Task: semantic factor assessment (semantic_factors:v1)

Assess ONE cluster against the active research context.

## decision_relevance (0.0–1.0)

How central this cluster is to the research mode, target entities,
market, and decision context supplied in the payload.

- competitor mode: competitor pricing, launches, features, positioning,
  and channel moves are highly relevant.
- Generic industry news unrelated to the research target is low.

Return a short `decision_relevance_rationale`.

## semantic_novelty (0.0–1.0, may be omitted)

Is this a genuinely new phenomenon, terminology, competitor form, or
pain point? This is DIAGNOSTIC metadata: it informs weak-signal
detection and the debug trail. It never overwrites the code-computed
novelty factor.

## commercial_intent (0.0–1.0, may be omitted)

Does the evidence express buying behaviour, willingness to pay, a buying
objection, or vendor selection? Diagnostic only.

## early_signal (boolean, may be omitted)

True when the cluster looks like the early stage of something that could
matter — new workaround, new objection, new channel behaviour, small
competitor gaining repeated mentions.

## Output rules

- Never invent evidence ids.
- Do NOT output recommendations, advice, or next steps.
- Forbidden phrasing: "you should", "recommend", "target", "invest",
  "increase budget".
