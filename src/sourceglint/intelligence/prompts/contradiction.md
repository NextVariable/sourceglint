# Task: support vs contradiction (contradiction:v1)

Given one cluster's claim and its evidence, decide which items SUPPORT
the claim and which CONTRADICT it.

## Classification kinds

- `factual` — the items assert incompatible facts
  ("price increased" vs "price unchanged").
- `experience` — the facts agree but reported experience differs
  ("translation quality improved a lot" vs "translation still unusable").
- `contextual` — the disagreement is a SEGMENT difference
  (enterprise users positive vs consumer users negative).
  This is NOT a factual contradiction; do not escalate it.

## Output rules

- `supporting_evidence_ids` and `counter_evidence_ids` may only contain
  ids given to you. Never invent an id.
- An id must never appear in both lists.
- If nothing contradicts the claim, return an empty
  `counter_evidence_ids` and `kind: none`.
- `confidence` is 0.0–1.0.

Do not output recommendations or advice.
