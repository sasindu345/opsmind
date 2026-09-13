import pytest
from fastapi.testclient import TestClient

from src.infrastructure.interfaces import ApplicationRecord
from src.infrastructure.local.repository import SQLiteApplicationRepository
from src.main import app


@pytest.fixture
def temp_app_repo(tmp_path):
    db_file = tmp_path / "test_apps.db"
    return SQLiteApplicationRepository(db_path=db_file)


@pytest.mark.asyncio
async def test_sqlite_application_crud(temp_app_repo):
    # 1. Save application
    record = ApplicationRecord(
        app_id="payment-service",
        name="Payment Service",
        description="Core payment processing pipeline",
        environment="production",
        owner_team="payments",
        health_url="https://api.example.com/health",
        probe_interval_seconds=30,
        health_status="healthy",
    )
    saved_id = await temp_app_repo.save_application(record)
    assert saved_id == "payment-service"

    # 2. Get application
    fetched = await temp_app_repo.get_application("payment-service")
    assert fetched is not None
    assert fetched.name == "Payment Service"
    assert fetched.environment == "production"
    assert fetched.owner_team == "payments"
    assert fetched.probe_interval_seconds == 30
    assert fetched.health_status == "healthy"

    # 3. List applications
    all_apps = await temp_app_repo.list_applications()
    assert len(all_apps) == 1
    assert all_apps[0].app_id == "payment-service"

    filtered = await temp_app_repo.list_applications(environment="staging")
    assert len(filtered) == 0

    # 4. Update application
    updated = await temp_app_repo.update_application(
        "payment-service",
        {"health_status": "degraded", "current_latency_ms": 320.5},
    )
    assert updated is not None
    assert updated.health_status == "degraded"
    assert updated.current_latency_ms == 320.5

    # 5. Delete application
    deleted = await temp_app_repo.delete_application("payment-service")
    assert deleted is True

    gone = await temp_app_repo.get_application("payment-service")
    assert gone is None


def test_api_application_crud():
    with TestClient(app) as client:
        # 1. Create application
        create_payload = {
            "app_id": "cart-api",
            "name": "Cart API",
            "description": "User shopping cart microservice",
            "environment": "staging",
            "owner_team": "checkout",
            "health_url": "https://httpbin.org/status/200",
            "probe_interval_seconds": 15,
        }
        resp = client.post("/api/v1/applications", json=create_payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["app_id"] == "cart-api"
        assert data["name"] == "Cart API"
        assert data["environment"] == "staging"
        assert data["health_url"] == "https://httpbin.org/status/200"

        # 2. Duplicate rejection
        dup_resp = client.post("/api/v1/applications", json=create_payload)
        assert dup_resp.status_code == 409

        # 3. List applications
        list_resp = client.get("/api/v1/applications")
        assert list_resp.status_code == 200
        apps = list_resp.json()
        assert any(a["app_id"] == "cart-api" for a in apps)

        # 4. Get by ID
        get_resp = client.get("/api/v1/applications/cart-api")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Cart API"

        # 5. Patch application
        patch_resp = client.patch(
            "/api/v1/applications/cart-api",
            json={"description": "Updated shopping cart service", "health_status": "healthy"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["description"] == "Updated shopping cart service"

        # 6. Delete application
        del_resp = client.delete("/api/v1/applications/cart-api")
        assert del_resp.status_code == 204

        # 7. Verify deletion
        not_found_resp = client.get("/api/v1/applications/cart-api")
        assert not_found_resp.status_code == 404
