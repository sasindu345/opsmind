from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.interfaces import (
    ApplicationRecord,
    HealthProbeSnapshot,
)
from src.infrastructure.local.repository import SQLiteApplicationRepository
from src.main import app


@pytest.fixture
def temp_app_repo(tmp_path):
    db_file = tmp_path / "test_metrics_apps.db"
    return SQLiteApplicationRepository(db_path=db_file)


@pytest.mark.asyncio
async def test_metrics_endpoint_empty_and_populated(temp_app_repo):
    from src.api import routes_applications, routes_metrics

    app.dependency_overrides[routes_applications._get_repo] = lambda: temp_app_repo
    app.dependency_overrides[routes_metrics._get_repo] = lambda: temp_app_repo
    try:
        # 1. Register test app
        app_record = ApplicationRecord(
            app_id="metrics-test-service",
            name="Metrics Test Service",
            environment="production",
            owner_team="telemetry",
            health_url="https://api.test.internal/health",
            probe_interval_seconds=30,
        )
        await temp_app_repo.save_application(app_record)

        with TestClient(app) as client:
            # 2. Test non-existent application 404
            resp = client.get("/api/v1/applications/non-existent/metrics")
            assert resp.status_code == 404
            assert "not found" in resp.json()["detail"].lower()

            # 3. Test invalid range 400
            resp = client.get("/api/v1/applications/metrics-test-service/metrics?range=30d")
            assert resp.status_code == 400
            assert "invalid range" in resp.json()["detail"].lower()

            # 4. Test empty metrics (0 snapshots)
            resp = client.get("/api/v1/applications/metrics-test-service/metrics?range=24h")
            assert resp.status_code == 200
            data = resp.json()
            assert data["app_id"] == "metrics-test-service"
            assert data["range"] == "24h"
            assert data["total_probes"] == 0
            assert data["uptime_percent"] == 100.0
            assert data["avg_latency_ms"] == 0.0
            assert data["p95_latency_ms"] == 0.0
            assert data["error_rate_percent"] == 0.0
            assert len(data["series"]) == 96  # 24h * 4 (15-min buckets)
            assert len(data["availability_segments"]) == 24
            assert all(seg["status"] == "nodata" for seg in data["availability_segments"])

            # 5. Insert probe snapshots across the past 2 hours
            now = datetime.now(UTC)
            snapshots = [
                HealthProbeSnapshot(
                    probe_id="p1",
                    app_id="metrics-test-service",
                    timestamp=now - timedelta(minutes=10),
                    http_status=200,
                    latency_ms=120.0,
                    is_success=True,
                ),
                HealthProbeSnapshot(
                    probe_id="p2",
                    app_id="metrics-test-service",
                    timestamp=now - timedelta(minutes=8),
                    http_status=200,
                    latency_ms=180.0,
                    is_success=True,
                ),
                HealthProbeSnapshot(
                    probe_id="p3",
                    app_id="metrics-test-service",
                    timestamp=now - timedelta(minutes=5),
                    http_status=500,
                    latency_ms=300.0,
                    is_success=False,
                    error_message="HTTP 500 Internal Server Error",
                ),
                HealthProbeSnapshot(
                    probe_id="p4",
                    app_id="metrics-test-service",
                    timestamp=now - timedelta(minutes=2),
                    http_status=200,
                    latency_ms=150.0,
                    is_success=True,
                ),
            ]
            for s in snapshots:
                await temp_app_repo.save_probe_snapshot(s)

            # 6. Fetch metrics for 1h
            resp_1h = client.get("/api/v1/applications/metrics-test-service/metrics?range=1h")
            assert resp_1h.status_code == 200
            data_1h = resp_1h.json()
            assert data_1h["total_probes"] == 4
            # 3 successes out of 4 = 75.0%
            assert data_1h["uptime_percent"] == 75.0
            assert data_1h["error_rate_percent"] == 25.0
            # Latencies: 120, 180, 300, 150 -> sum = 750 / 4 = 187.5
            assert data_1h["avg_latency_ms"] == 187.5
            assert data_1h["p95_latency_ms"] == 300.0

            # Verify series has non-zero points
            points_with_data = [p for p in data_1h["series"] if p["total_count"] > 0]
            assert len(points_with_data) > 0
            total_in_points = sum(p["total_count"] for p in points_with_data)
            assert total_in_points == 4

            # 7. Check availability segments
            segments_with_data = [
                s for s in data_1h["availability_segments"] if s["status"] != "nodata"
            ]
            assert len(segments_with_data) > 0

            # 8. Check 6h and 7d ranges return 200
            url_prefix = "/api/v1/applications/metrics-test-service/metrics"
            assert client.get(f"{url_prefix}?range=6h").status_code == 200
            assert client.get(f"{url_prefix}?range=7d").status_code == 200
    finally:
        app.dependency_overrides.clear()
