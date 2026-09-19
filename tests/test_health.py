from fastapi.testclient import TestClient

from src.main import app


def test_healthz_returns_ok():
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_subsystems():
    with TestClient(app) as client:
        response = client.get("/readyz")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["llm"]["provider"] in {"gemini", "ollama"}
    assert "slack_enabled" in body


def test_dashboard_endpoint_returns_html():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "OpsMind" in response.text
    assert "Live Incident Stream" in response.text
