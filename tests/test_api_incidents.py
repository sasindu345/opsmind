from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from src.infrastructure.interfaces import IncidentRecord
from src.main import app


def test_incidents_api_lifecycle(monkeypatch):
    mock_repo = MagicMock()
    sample_rec = IncidentRecord(
        incident_id="test-api-inc-1",
        service="checkout",
        environment="production",
        severity="high",
        status="open",
        created_at=datetime.now(UTC),
        title="OOMKilled pod",
        probable_cause="Memory limit exceeded",
        confidence=0.9,
        evidence_summary=["[ERROR] OOMKilled"],
        timeline_json=[
            {"timestamp": "2026-09-08T10:00:00Z", "source": "log", "description": "Pod crash"}
        ],
    )

    # Mock repository methods
    mock_repo.list_incidents = AsyncMock(return_value=[sample_rec])
    mock_repo.get_incident = AsyncMock(return_value=sample_rec)
    mock_repo.update_status = AsyncMock(return_value=True)

    monkeypatch.setattr(
        "src.api.routes_incidents.get_incident_repository",
        lambda settings=None: mock_repo,
    )

    with TestClient(app) as client:
        # 1. List
        resp = client.get("/api/v1/incidents")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["incident_id"] == "test-api-inc-1"

        # 2. Get
        resp = client.get("/api/v1/incidents/test-api-inc-1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["service"] == "checkout"
        assert body["status"] == "open"

        # 3. Acknowledge
        resp = client.post("/api/v1/incidents/test-api-inc-1/acknowledge")
        assert resp.status_code == 200
        assert resp.json()["status"] == "acknowledged"

        # 4. Resolve
        resp = client.post("/api/v1/incidents/test-api-inc-1/resolve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"

        # 5. Timeline
        resp = client.get("/api/v1/incidents/test-api-inc-1/timeline")
        assert resp.status_code == 200
        timeline = resp.json()
        assert len(timeline) == 1
        assert timeline[0]["description"] == "Pod crash"

        # 6. Postmortem
        resp = client.post("/api/v1/incidents/test-api-inc-1/postmortem")
        assert resp.status_code == 200
        assert "access_url" in resp.json()


def test_get_nonexistent_incident_returns_404(monkeypatch):
    mock_repo = MagicMock()
    mock_repo.get_incident = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "src.api.routes_incidents.get_incident_repository",
        lambda settings=None: mock_repo,
    )

    with TestClient(app) as client:
        resp = client.get("/api/v1/incidents/nonexistent-id")
    assert resp.status_code == 404
