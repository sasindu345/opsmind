from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.core.security import SSRFError, SSRFValidator, ValidatedTarget
from src.core.synthetic import (
    ProbeFetchResult,
    SyntheticHealthWorker,
    execute_probe,
    probe_incident_id,
)
from src.infrastructure.interfaces import ApplicationRecord
from src.infrastructure.local.repository import (
    SQLiteApplicationRepository,
    SQLiteIncidentRepository,
)
from src.llm.schemas import IncidentStatus
from src.main import app


class _PublicValidator:
    def validate_url(self, url: str) -> ValidatedTarget:
        return ValidatedTarget(
            url=url,
            hostname="checkout.example",
            port=80,
            resolved_ip="1.1.1.1",
            scheme="http",
        )


def _status_fetch(status_code: int, location: str | None = None):
    async def fetch(target, timeout=5.0):
        return ProbeFetchResult(status_code=status_code, location=location)

    return fetch


@pytest.fixture
def repos(tmp_path):
    db = tmp_path / "probes.db"
    return SQLiteApplicationRepository(db_path=db), SQLiteIncidentRepository(db_path=db)


async def _save_app(app_repo, failures: int = 0, status: str = "unknown") -> ApplicationRecord:
    record = ApplicationRecord(
        app_id="checkout-api",
        name="Checkout API",
        environment="production",
        health_url="http://checkout.example/healthz",
        probe_interval_seconds=30,
        health_status=status,
        consecutive_failures=failures,
    )
    await app_repo.save_application(record)
    stored = await app_repo.get_application("checkout-api")
    assert stored is not None
    return stored


@pytest.mark.asyncio
async def test_three_failures_open_an_incident(repos):
    app_repo, incident_repo = repos
    app = await _save_app(app_repo)

    for expected in (1, 2):
        outcome = await execute_probe(
            app,
            app_repo,
            incident_repo,
            validator=_PublicValidator(),
            fetch=_status_fetch(500),
        )
        assert outcome.is_success is False
        assert outcome.consecutive_failures == expected
        assert outcome.incident_opened is False
        app = await app_repo.get_application("checkout-api")

    third = await execute_probe(
        app,
        app_repo,
        incident_repo,
        validator=_PublicValidator(),
        fetch=_status_fetch(500),
    )
    assert third.incident_opened is True
    assert third.status == "critical"
    incident = await incident_repo.get_incident(probe_incident_id("checkout-api"))
    assert incident is not None
    assert incident.status == IncidentStatus.OPEN.value
    assert "unavailable" in incident.title.lower()


@pytest.mark.asyncio
async def test_recovery_resets_failures_and_resolves_incident(repos):
    app_repo, incident_repo = repos
    app = await _save_app(app_repo, failures=2, status="degraded")
    await execute_probe(
        app,
        app_repo,
        incident_repo,
        validator=_PublicValidator(),
        fetch=_status_fetch(500),
    )
    app = await app_repo.get_application("checkout-api")
    recovered = await execute_probe(
        app,
        app_repo,
        incident_repo,
        validator=_PublicValidator(),
        fetch=_status_fetch(200),
    )
    assert recovered.is_success is True
    assert recovered.consecutive_failures == 0
    assert recovered.status == "healthy"
    assert recovered.recovered is True
    incident = await incident_repo.get_incident(probe_incident_id("checkout-api"))
    assert incident is not None
    assert incident.status == IncidentStatus.RESOLVED.value


@pytest.mark.asyncio
async def test_redirect_to_metadata_ip_is_rejected(repos):
    app_repo, incident_repo = repos
    record = ApplicationRecord(
        app_id="checkout-api",
        name="Checkout API",
        health_url="http://1.1.1.1/healthz",
        health_status="unknown",
    )
    await app_repo.save_application(record)
    app = await app_repo.get_application("checkout-api")
    assert app is not None

    async def fetch(target, timeout=5.0):
        if "169.254.169.254" in target.url:
            raise AssertionError("pinned fetch must not follow a blocked redirect")
        return ProbeFetchResult(status_code=302, location="http://169.254.169.254/latest")

    with pytest.raises(SSRFError, match="SSRF Protection Triggered"):
        await execute_probe(
            app,
            app_repo,
            incident_repo,
            validator=SSRFValidator(),
            fetch=fetch,
        )


@pytest.mark.asyncio
async def test_worker_skips_apps_that_were_probed_recently(repos):
    app_repo, incident_repo = repos
    app = await _save_app(app_repo)
    await app_repo.update_application(
        app.app_id,
        {"last_probe_at": datetime.now(UTC) - timedelta(seconds=5)},
    )
    calls = {"count": 0}

    async def fetch(target, timeout=5.0):
        calls["count"] += 1
        return ProbeFetchResult(status_code=200)

    worker = SyntheticHealthWorker(
        app_repo,
        incident_repo,
        validator=_PublicValidator(),
        fetch=fetch,
    )
    outcomes = await worker.run_once()
    assert outcomes == []
    assert calls["count"] == 0


def test_probe_api_rejects_metadata_and_localhost():
    with TestClient(app) as client:
        for app_id, health_url in (
            ("metadata-target", "http://169.254.169.254/latest/meta-data"),
            ("localhost-target", "http://localhost:8000/healthz"),
        ):
            created = client.post(
                "/api/v1/applications",
                json={
                    "app_id": app_id,
                    "name": app_id,
                    "health_url": health_url,
                },
            )
            assert created.status_code in (201, 409)
            probed = client.post(f"/api/v1/applications/{app_id}/probe")
            assert probed.status_code == 400
            assert "SSRF Protection Triggered" in probed.json()["detail"]
            client.delete(f"/api/v1/applications/{app_id}")
