from sourceglint.health import build_report


def test_keyless_reddit_does_not_require_oauth(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    report = build_report()
    reddit = next(row for row in report["sources"] if row["source"] == "reddit")
    assert reddit["state"] == "READY_UNVERIFIED"
    assert reddit["missing_credentials"] == []
    assert report["network_probed"] is False


def test_health_does_not_expose_a_secret_or_certify_live_access(monkeypatch):
    secret = "private-test-secret-value"
    monkeypatch.setenv("X_BEARER_TOKEN", secret)
    report = build_report()
    assert secret not in str(report)
    x = next(row for row in report["sources"] if row["source"] == "x")
    assert x["state"] == "READY_UNVERIFIED"
