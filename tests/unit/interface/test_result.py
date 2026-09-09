"""Phase 7 §20–§21, §56 — SkillResult / Status tests."""
from __future__ import annotations

from gtm_intelligence.interface.result import SkillResult, Status


class TestStatusTaxonomy:
    def test_only_four_external_statuses(self):
        assert {s.value for s in Status} == {
            "SUCCESS", "PARTIAL", "NO_EVIDENCE", "FAILED",
        }

    def test_ok_classification(self):
        assert SkillResult(status=Status.SUCCESS).ok
        assert SkillResult(status=Status.PARTIAL).ok
        assert SkillResult(status=Status.NO_EVIDENCE).ok
        assert not SkillResult(status=Status.FAILED).ok


class TestSkillResult:
    def test_to_dict_never_dumps_internal_objects(self):
        r = SkillResult(
            status=Status.SUCCESS,
            brief_markdown="# GTM Intelligence Brief",
            warnings=("a", "b"),
            stage_statuses={"research": "ok", "signal": "degraded"},
            diagnostics={"debug": True},
        )
        d = r.to_dict()
        assert d["status"] == "SUCCESS"
        assert d["brief_markdown"].startswith("# GTM")
        assert d["warnings"] == ["a", "b"]
        assert d["stage_statuses"]["research"] == "ok"
        # diagnostics serialized as dict (host-debug only)
        assert d["diagnostics"]["debug"] is True
