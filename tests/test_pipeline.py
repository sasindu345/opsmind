import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config.settings import get_settings
from src.api.schemas import LogBatch
from src.core.anomaly_detector import AnomalyMethod, AnomalyRecord
from src.core.correlator import DeploymentRecord
from src.core.pipeline import analyze_logs
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

    report = tmp_path / Path(body["report_path"]).name
    assert report.exists()
    text = report.read_text()
    assert "Checkout pods OOMKilled" in text
    assert "kubectl set resources" in text


def test_endpoint_degrades_gracefully_when_llm_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.llm.client.litellm.acompletion", FakeCompletion("garbage", "still garbage")
    )

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


@pytest.mark.asyncio
async def test_analyze_logs_with_multi_source_telemetry(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.llm.client.litellm.acompletion", FakeCompletion(json.dumps(VALID_ANALYSIS))
    )
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "reports_dir", tmp_path)

    now = datetime(2026, 9, 6, 15, 0, 0, tzinfo=UTC)
    batch = LogBatch(
        service="checkout",
        environment="production",
        logs=LOGS,
        occurred_at=now,
        generate_report=True,
    )

    anomalies = [
        AnomalyRecord(
            metric_name="memory_utilization",
            timestamp=now - timedelta(minutes=2),
            value=98.5,
            baseline_value=45.0,
            threshold_value=85.0,
            score=4.2,
            method=AnomalyMethod.ZSCORE,
            direction="spike",
            is_anomaly=True,
        )
    ]

    deployments = [
        DeploymentRecord(
            commit_sha="c0ffee123456",
            author="carol@example.com",
            service="checkout",
            environment="production",
            timestamp=now - timedelta(minutes=4),
            message="Reduce pod container memory limit",
            changed_files=["deploy/helm/values.yaml"],
        )
    ]

    result = await analyze_logs(
        batch,
        settings=settings,
        anomalies=anomalies,
        deployments=deployments,
    )

    assert result.service == "checkout"
    assert result.degraded is False
    assert len(result.timeline) == 3  # deployment, metric anomaly, log triage
    assert any("c0ffee1" in ev for ev in result.observed_evidence)
    assert any("memory_utilization" in ev for ev in result.observed_evidence)
    assert result.report_path is not None
    assert Path(result.report_path).exists()
