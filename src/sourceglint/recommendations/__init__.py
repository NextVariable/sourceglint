"""Phase 6B — GTM Implication & Recommendation Layer.

Consumes validated Phase 6A FACT / INFERENCE insights and produces a
traceable, explainable, prioritized Recommendation Set (PRD §1, §48).

Pipeline:

    Validated FACT / INFERENCE Insights
      → prepare_decision_context()          context.py      (code)
      → generate_candidate_recommendations() generate.py     (model + code)
      → validate_support()                  support.py      (code gate)
      → specificity guard                   specificity.py  (code gate)
      → assess_actionability()              assess.py       (model + code)
      → derive priority / risk              assess.py       (code)
      → detect_conflicts()                  conflicts.py    (model + code)
      → deduplicate_recommendations()       dedup.py        (code + model)
      → validate RECOMMENDATION schema      validation gate
      → RecommendationPipelineResult

STOP BOUNDARY (PRD §48): output is a Recommendation Set only. No Final
Intelligence Brief, no renderer, no Skill Interface, no host packaging,
no side effects (PRD §38).
"""
