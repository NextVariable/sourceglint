"""Phase 6A §12–§13, §37 — FACT grounding validation (code-side).

The model owns statement wording; code rejects statements that assert
more than the cited evidence can support:

  - unsupported quantification (§12, §37): a number/percent in the
    statement that is not backed by code-computed counts or by the text
    of evidence owned by the cited signals;
  - unsupported causality (§12): a causal connective ("because of",
    "caused", ...) that does not also appear in that evidence text;
  - unsupported universality (§13): a blanket generalization ("users
    generally", "the market shows", ...) not present in that evidence;
  - unsupported future (§12): a predictive assertion ("will dominate",
    "is expected to", ...) not present in that evidence.

VOC exception (§28): statements that REPORT user speech (start with a
reporting prefix such as "users say") describe what users claim, not
what the model asserts — textual grounding rules are not applied.
Numeric grounding still applies (a quoted number must exist somewhere
in the signal's evidence or be a code-computed count).
"""
from __future__ import annotations

import pytest

from sourceglint.insights.grounding import check_fact_grounding

# evidence pool: one signal (sig_a) owns ev_1 + ev_2 with real text.


def _evidence() -> dict:
    return {
        "ev_1": {
            "evidence_id": "ev_1",
            "snippet": "Several users complained about the price hike from $10 to $15.",
            "title": "Pricing complaints",
        },
        "ev_2": {
            "evidence_id": "ev_2",
            "snippet": "A competitor lowered its price due to churn.",
            "title": "Competitor move",
        },
    }


def _map() -> dict:
    return {"sig_a": {"ev_1", "ev_2"}}


def _check(statement: str, **kw) -> list[str]:
    return check_fact_grounding(
        statement,
        signal_ids=("sig_a",),
        evidence_ids=("ev_1",),
        signal_evidence_map=_map(),
        evidence_by_id=_evidence(),
        **kw,
    )


class TestUnsupportedQuantification:
    def test_number_backed_by_evidence_text_passes(self):
        # $10 and $15 both appear in ev_1's text.
        assert _check(
            "The listed price increased from $10 to $15 per user."
        ) == []

    def test_percentage_backed_by_text_passes(self):
        text_ev = {"ev_p": {"snippet": "The vendor announced a list-price cut of 50%."}}
        assert check_fact_grounding(
            "The vendor's list price dropped 50% this month.",
            signal_ids=("sig_p",),
            evidence_ids=("ev_p",),
            signal_evidence_map={"sig_p": {"ev_p"}},
            evidence_by_id=text_ev,
        ) == []

    def test_fabricated_percentage_rejected(self):
        # "80%" appears nowhere in the signal's evidence text.
        violations = _check("80% of users complained about the price.")
        assert any("80" in v and "unsupported quantification" in v for v in violations)

    def test_fabricated_absolute_count_rejected(self):
        violations = _check("Over 1,200 users complained about the price.")
        assert any("1200" in v and "unsupported quantification" in v for v in violations)

    def test_code_computed_count_allowed(self):
        # current_count=2 / baseline_count=1 are code-provided (§37).
        counts = {"sig_a": (2, 1)}
        assert _check(
            "The issue appears in 2 current-window evidence items and 1 baseline item.",
            code_counts=counts,
        ) == []

    def test_cited_evidence_length_allowed(self):
        # len(cited evidence_ids) is code-computable (§37): ev_1 + ev_2.
        assert check_fact_grounding(
            "The claim is backed by 2 evidence items.",
            signal_ids=("sig_a",),
            evidence_ids=("ev_1", "ev_2"),
            signal_evidence_map=_map(),
            evidence_by_id=_evidence(),
        ) == []


class TestUnsupportedCausality:
    def test_causal_phrase_in_evidence_text_passes(self):
        # ev_2 text carries "due to churn".
        assert _check("The competitor's price change was due to churn.") == []

    def test_unsupported_causality_rejected(self):
        violations = _check(
            "The price increase caused users to leave for free alternatives."
        )
        assert any("unsupported causality" in v for v in violations)


class TestUnsupportedUniversality:
    def test_denied_generalization_is_not_an_assertion(self):
        assert _check("This is not evidence of widespread complaints.") == []

    def test_disclaimer_does_not_hide_a_later_assertion(self):
        violations = _check("This is not evidence of widespread complaints. Widespread dissatisfaction is clear.")
        assert any("unsupported universality" in v for v in violations)

    def test_universal_claim_supported_by_text_passes(self):
        # ev_1 text: "Several users complained..."
        assert _check("Several users complained about the price hike.") == []

    def test_unsupported_universality_rejected(self):
        violations = _check("Users generally dislike the product.")
        assert any("unsupported universality" in v for v in violations)

    def test_small_evidence_market_generalization_rejected(self):
        violations = _check("The market is shifting toward free tools.")
        assert any("unsupported universality" in v for v in violations)


class TestUnsupportedFuture:
    def test_future_claim_rejected(self):
        violations = _check("This product will dominate the market.")
        assert any("unsupported future" in v for v in violations)

    def test_future_phrase_backed_by_text_passes(self):
        text_ev = {
            "ev_9": {"snippet": "Analysts expect the vendor is poised to lead the segment."}
        }
        assert check_fact_grounding(
            "Analysts say the vendor is poised to lead the segment.",
            signal_ids=("sig_z",),
            evidence_ids=("ev_9",),
            signal_evidence_map={"sig_z": {"ev_9"}},
            evidence_by_id=text_ev,
        ) == []


class TestVOCException:
    def test_reported_user_desire_not_rejected_for_causality(self):
        # Reported speech describing users' stated reason — not a model
        # causal assertion (§28).
        assert _check(
            "Users say they left because of the price increase."
        ) == []

    def test_reported_user_desire_not_rejected_for_future(self):
        assert _check(
            "One source reports the tool is expected to add Japanese."
        ) == []

    def test_voc_quote_numbers_still_grounded(self):
        # Numeric grounding still applies inside reported speech.
        violations = _check("Users say 90% of their team quit.")
        assert any("90" in v and "unsupported quantification" in v for v in violations)

@pytest.mark.parametrize('statement,valid', [
    ('The issue was reported on September 9, 2026.', True),
    ('The issue was reported on 2026-09-09.', True),
    ('The issue was reported on September 23, 2026.', False),
    ('The issue affected 9% of users.', False),
    ('On September 9, 2026, it affected 9% of users.', False),
])
def test_publication_dates_are_dates_not_numeric_claims(statement, valid):
    violations = check_fact_grounding(
        statement, signal_ids=('sig',), evidence_ids=('ev',),
        signal_evidence_map={'sig': {'ev'}},
        evidence_by_id={'ev': {'snippet': 'A user reported an issue.',
                               'published_at': '2026-09-09T12:00:00Z'}},
    )
    assert (violations == []) is valid


def test_event_date_in_source_text_is_not_forced_to_publication_date():
    assert check_fact_grounding(
        'The vendor released the patch on September 9, 2026.',
        signal_ids=('sig',), evidence_ids=('ev',),
        signal_evidence_map={'sig': {'ev'}},
        evidence_by_id={'ev': {'snippet': 'Released on September 9, 2026.',
                               'published_at': '2026-09-23T12:00:00Z'}},
    ) == []
