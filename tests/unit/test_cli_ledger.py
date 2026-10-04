"""The exported run corpus must be usable and isolated from earlier research."""
import json

from sourceglint.cli import main
from sourceglint.intelligence.model import FakeIntelligenceModel
from sourceglint.pipeline.adapters import FakeSourceAdapter
import sourceglint.cli as cli


def test_cli_persists_retained_evidence_and_reports_its_path(tmp_path, monkeypatch, capsys):
    path = tmp_path / "run" / "evidence.jsonl"
    monkeypatch.setattr(cli, "_load_model", lambda spec: FakeIntelligenceModel())
    monkeypatch.setattr(cli, "_load_registry", lambda path: [{"name": "hacker_news", "enabled": True, "type": "community", "cost": "free", "auth_required": False, "credentials": [], "priority": 70, "capabilities": ["search"], "markets": ["global"], "languages": ["en"], "cache_ttl": 0}])
    monkeypatch.setattr(cli, "default_adapter_factory", lambda name, plan: FakeSourceAdapter(name, [{"source_type": "post", "source_native_id": "export-test", "url": "https://news.ycombinator.com/item?id=123", "title": "Recent example", "text": "A bounded observation." * 80, "raw_metadata": {"hn_comment_html": "original provider markup"}, "published_at": "2026-10-01T00:00:00Z"}]))
    assert main(["recent examples", "--host-sources-stdio", "--as-of", "2026-10-04T00:00:00Z", "--ledger", str(path), "--json"]) == 0
    artifact = json.loads(capsys.readouterr().out)
    record = json.loads(path.read_text())
    assert record["evidence_id"]
    assert record["published_at"] == "2026-10-01T00:00:00Z"
    assert artifact["diagnostics"]["evidence_ledger"] == str(path)
    assert artifact["diagnostics"]["evidence_count"] == 1
    raw_path = path.with_suffix(".raw.jsonl")
    rows = [json.loads(line) for line in raw_path.read_text().splitlines()]
    assert rows
    raw = rows[0]
    assert raw["record_kind"] == "unvalidated_source_observation"
    assert len(raw["record"]["text"]) > 280
    assert len(record["snippet"]) == 280
    assert raw["record"]["raw_metadata"]["hn_comment_html"] == "original provider markup"
    assert artifact["diagnostics"]["raw_source_archive"] == str(raw_path)


def test_cli_rejects_existing_nonempty_ledger_before_retrieval(tmp_path, monkeypatch, capsys):
    path = tmp_path / "evidence.jsonl"
    path.write_text("existing research\n")
    monkeypatch.setattr(cli, "_load_model", lambda spec: FakeIntelligenceModel())
    assert main(["recent examples", "--ledger", str(path)]) == 1
    assert "fresh path" in capsys.readouterr().err
    assert path.read_text() == "existing research\n"
