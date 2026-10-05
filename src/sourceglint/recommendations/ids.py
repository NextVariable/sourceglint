"""Phase 6B §27 — deterministic Recommendation identity.

Recommendation IDs are derived by CODE from stable structural inputs,
never from free-text wording:

    type=RECOMMENDATION
    + sorted supporting insight_ids
    + sorted GTM dimensions
    + action_class
    + normalized action_anchor

The full natural-language action is deliberately excluded from the hash
so minor wording drift does not change the identity (§27). The
action_anchor is a SHORT normalized model label ("entry_offer_test") —
when the model rewords a recommendation but keeps the anchor + support
chain + class + dimensions, the ID stays stable.

The output id satisfies the frozen common.schema.json insight_id pattern
(^ins_[a-z0-9_]{1,64}$) — RECOMMENDATION lives inside the Insight schema
and must reuse its id namespace (schema SoT beats the PRD §27 "rec_"
suggestion).
"""
from __future__ import annotations

import re
from typing import Iterable

from ..insights.ids import INSIGHT_ID_PREFIX, _digest

#: Normalized anchor form: 1..48 chars, lowercase alnum + underscore.
_ANCHOR_RE = re.compile(r"^[a-z0-9_]{1,48}$")

RECOMMENDATION = "RECOMMENDATION"


def normalize_action_anchor(raw: str) -> str:
    """Normalize a model-supplied action anchor into a stable slug.

    Lowercase, non-alnum → '_', collapse runs, strip edges, cap at 48.
    Empty result (all punctuation) becomes "action" — a recommendation
    still needs a distinguishing token inside its hash.
    """
    if not raw or not raw.strip():
        return "action"
    slug = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)[:48]
    return slug or "action"


def is_valid_action_anchor(value: str) -> bool:
    return bool(_ANCHOR_RE.match(value or ""))


def derive_recommendation_id(
    *,
    supporting_insight_ids: Iterable[str],
    gtm_dimensions: Iterable[str],
    action_class: str,
    action_anchor: str = "",
) -> str:
    """`ins_<sha256(RECOMMENDATION + sorted support + dims + class + anchor)>`."""
    insights = sorted({str(i) for i in supporting_insight_ids if str(i)})
    dims = sorted({str(d) for d in gtm_dimensions if str(d)})
    if not insights:
        raise ValueError("cannot derive a recommendation id without supporting insights")
    anchor = normalize_action_anchor(action_anchor)
    digest = _digest([
        RECOMMENDATION,
        *insights,
        *dims,
        str(action_class),
        anchor,
    ])
    return f"{INSIGHT_ID_PREFIX}{digest}"
