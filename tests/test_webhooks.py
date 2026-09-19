import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from config.settings import get_settings
from src.core.metrics import get_metrics_collector, sanitize_text
from src.core.worker import get_local_queue
from src.main import app


def test_prometheus_webhook_enqueues_alert():
    queue = get_local_queue()
    initial_q_size = queue._queue.qsize()

    payload = {
        "version": "4",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighLatencySpike",
                    "service": "checkout",
                    "severity": "critical",
                    "env": "production",
                },
                "annotations": {
                    "summary": "P99 latency above 2500ms",
                    "description": "Database queries taking over 2.5s",
                },
                "startsAt": "2026-09-08T10:00:00Z",
            }
        ],
    }

    with TestClient(app) as client:
        resp = client.post("/api/v1/webhooks/prometheus", json=payload)

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["service"] == "checkout"
    assert queue._queue.qsize() == initial_q_size + 1


def test_github_webhook_with_valid_hmac(monkeypatch):
    secret = "my-test-secret"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    get_settings.cache_clear()

    payload_dict = {
        "repository": {"name": "auth-service"},
        "head_commit": {
            "id": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "author": {"name": "alice"},
            "message": "Bump token TTL",
            "added": ["config.json"],
            "modified": [],
            "removed": [],
        },
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/webhooks/github",
            content=payload_bytes,
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": f"sha256={sig}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 202
    body = resp.json()
    assert body["service"] == "auth-service"
    assert body["status"] == "queued"


def test_github_webhook_with_invalid_hmac_rejected(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "super-secret")
    get_settings.cache_clear()

    payload_bytes = b'{"repository": {"name": "auth-service"}}'
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/webhooks/github",
            content=payload_bytes,
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": "sha256=invalid-signature",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 401
    assert "Invalid HMAC signature" in resp.json()["detail"]


def test_cloudwatch_alarm_webhook_enqueues():
    payload = {
        "AlarmName": "checkout-High5xxErrors",
        "NewStateValue": "ALARM",
        "NewStateReason": "Threshold Crossed: 1 datapoints [5.0] >= threshold [1.0].",
        "Trigger": {
            "MetricName": "HTTPCode_Target_5XX_Count",
            "Namespace": "AWS/ApplicationELB",
            "Dimensions": [{"name": "ServiceName", "value": "checkout"}],
        },
    }

    with TestClient(app) as client:
        resp = client.post("/api/v1/webhooks/cloudwatch", json=payload)

    assert resp.status_code == 202
    body = resp.json()
    assert body["service"] == "checkout"
    assert body["status"] == "queued"


def test_metrics_collector_and_secret_sanitization():
    collector = get_metrics_collector()
    collector.record_incident_detected("checkout", "critical")
    collector.record_llm_request("gemini-2.0-flash", success=True)
    collector.record_anomaly_detected("cpu", 3.4)

    flushed = collector.flush()
    assert len(flushed) >= 3

    sensitive_text = (
        "Error connecting to db using token=ghp_ABC12345678901234567890123456789012 "
        "and AKIAIOSFODNN7EXAMPLE"
    )
    sanitized = sanitize_text(sensitive_text)
    assert "ghp_" not in sanitized
    assert "AKIA" not in sanitized
    assert "[REDACTED]" in sanitized
