import json

from fastapi.testclient import TestClient

from src.main import app
from tests.test_llm_schemas import VALID_ANALYSIS, FakeCompletion

LOGS = [
    f"2026-08-25T10:{i:02d}:00Z ERROR OOMKilled pod checkout-7d9f{i} memory limit exceeded"
    for i in range(30)
] + ["2026-08-25T10:31:00Z INFO connection pool resized to 20"]


def _post(monkeypatch, tmp_path, **overrides):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.llm.client.litellm.acompletion", FakeCompletion(json.dumps(VALID_ANALYSIS))
    )
    from config.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "reports_dir", tmp_path)

    payload = {"service": "checkout", "environment": "production", "logs": LOGS, **overrides}
    with TestClient(app) as client:
        return client.post("/api/v1/analyze/logs", json=payload)


def test_endpoint_returns_analysis_and_writes_report(monkeypatch, tmp_path):
    response = _post(monkeypatch, tmp_path)
    assert response.status_code == 200
    body = response.json()

    assert body["analysis"]["probable_cause"].startswith("Memory limit")
    assert body["degraded"] is False
    assert body["lines_ingested"] == len(LOGS)
    assert len(body["clusters"]) == 2
    assert body["token_reduction"] > 0.8

    report = tmp_path / __import__("pathlib").Path(body["report_path"]).name
    assert report.exists()
    text = report.read_text()
    assert "Checkout pods OOMKilled" in text
    assert "kubectl set resources" in text


def test_endpoint_degrades_gracefully_when_llm_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.llm.client.litellm.acompletion", FakeCompletion("garbage", "still garbage")
    )
    from config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(get_settings(), "reports_dir", tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/analyze/logs", json={"service": "checkout", "logs": LOGS}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert body["analysis"]["confidence"] < 0.4
    assert "OOMKilled" in body["analysis"]["probable_cause"]


def test_empty_logs_are_rejected():
    with TestClient(app) as client:
        response = client.post("/api/v1/analyze/logs", json={"service": "x", "logs": ["  "]})
    assert response.status_code == 422
