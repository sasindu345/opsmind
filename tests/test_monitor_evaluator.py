"""User-configured metric monitors.

Covers the evaluator's pure logic, the breach-to-incident path, and the CRUD
API. The product requirement is that a user can configure what to watch and get
an AI-backed fix when it breaches.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from config.settings import Settings, get_settings
from src.core.monitor_evaluator import evaluate_monitor, monitor_incident_id
from src.core.synthetic import evaluate_monitors_for_app
from src.infrastructure.interfaces import (
    ApplicationRecord,
    HealthProbeSnapshot,
    MetricMonitorRecord,
)
from src.infrastructure.local.repository import (
    SQLiteApplicationRepository,
    SQLiteIncidentRepository,
)
from src.main import app as fastapi_app

SETTINGS = Settings()


def _snapshots(values: list[float], *, success: bool = True, spacing: int = 30):
    """Build probe samples, newest last, spaced `spacing` seconds apart."""
    now = datetime.now(UTC)
    total = len(values)
    return [
        HealthProbeSnapshot(
            probe_id=f"probe-{index}",
            app_id="checkout-api",
            timestamp=now - timedelta(seconds=(total - 1 - index) * spacing),
            http_status=200 if success else 503,
            latency_ms=value,
            is_success=success,
        )
        for index, value in enumerate(values)
    ]


def _monitor(**overrides) -> MetricMonitorRecord:
    defaults = dict(
        monitor_id="mon-1",
        app_id="checkout-api",
        name="Slow response time",
        signal_source="probe_latency",
        mode="threshold",
        comparison="gt",
        threshold_value=500.0,
        window_seconds=900,
        min_samples=3,
        consecutive_breaches_required=2,
        severity="HIGH",
    )
    defaults.update(overrides)
    return MetricMonitorRecord(**defaults)


def test_latency_threshold_breaches_on_the_latest_sample():
    breach = evaluate_monitor(_monitor(), _snapshots([100, 120, 900]), settings=SETTINGS)
    assert breach is not None
    assert breach.observed_value == 900
    assert breach.threshold_value == 500.0
    assert "above" in breach.summary


def test_latency_below_the_threshold_does_not_breach():
    assert evaluate_monitor(_monitor(), _snapshots([100, 120, 130]), settings=SETTINGS) is None


def test_disabled_monitor_is_never_evaluated():
    monitor = _monitor(enabled=False)
    assert evaluate_monitor(monitor, _snapshots([5000, 5000, 5000]), settings=SETTINGS) is None


def test_insufficient_samples_defers_evaluation():
    monitor = _monitor(min_samples=5)
    assert evaluate_monitor(monitor, _snapshots([900, 900]), settings=SETTINGS) is None


def test_samples_outside_the_window_are_ignored():
    monitor = _monitor(window_seconds=60, min_samples=1)
    # 30s spacing over 5 samples puts the older ones outside a 60s window.
    breach = evaluate_monitor(monitor, _snapshots([5000, 5000, 5000, 100, 100]), settings=SETTINGS)
    assert breach is None


def test_lt_comparison_supports_availability_monitors():
    monitor = _monitor(
        signal_source="probe_availability",
        comparison="lt",
        threshold_value=99.0,
    )
    breach = evaluate_monitor(
        monitor,
        _snapshots([0, 0, 0], success=False),
        settings=SETTINGS,
    )
    assert breach is not None
    assert breach.observed_value == 0.0
    assert "below" in breach.summary


def test_error_rate_monitor_averages_across_the_window():
    monitor = _monitor(signal_source="probe_error_rate", comparison="gt", threshold_value=50.0)
    assert evaluate_monitor(monitor, _snapshots([1, 1, 1], success=False), settings=SETTINGS)
    assert evaluate_monitor(monitor, _snapshots([1, 1, 1], success=True), settings=SETTINGS) is None


def test_anomaly_mode_reuses_the_zscore_detector():
    monitor = _monitor(mode="anomaly", anomaly_method="zscore", min_samples=5)
    steady = [100.0] * 20
    breach = evaluate_monitor(monitor, _snapshots([*steady, 5000.0]), settings=SETTINGS)
    assert breach is not None
    assert breach.mode == "anomaly"
    assert "unusual" in breach.summary


def test_anomaly_mode_is_quiet_on_a_steady_series():
    monitor = _monitor(mode="anomaly", min_samples=5)
    assert evaluate_monitor(monitor, _snapshots([100.0] * 20), settings=SETTINGS) is None


def test_unknown_comparison_is_rejected_rather_than_guessed():
    assert (
        evaluate_monitor(
            _monitor(comparison="approximately"), _snapshots([900, 900, 900]), settings=SETTINGS
        )
        is None
    )


@pytest.fixture
def repos(tmp_path):
    db = tmp_path / "monitors.db"
    return SQLiteApplicationRepository(db_path=db), SQLiteIncidentRepository(db_path=db)


async def _register_app(app_repo) -> ApplicationRecord:
    await app_repo.save_application(
        ApplicationRecord(
            app_id="checkout-api",
            name="Checkout API",
            environment="production",
            health_url="http://checkout.example/healthz",
        )
    )
    record = await app_repo.get_application("checkout-api")
    assert record is not None
    return record


@pytest.mark.asyncio
async def test_monitor_round_trips_through_the_repository(repos):
    app_repo, _ = repos
    await _register_app(app_repo)
    await app_repo.save_monitor(_monitor())

    stored = await app_repo.get_monitor("mon-1")
    assert stored is not None
    assert stored.name == "Slow response time"
    assert stored.threshold_value == 500.0
    assert stored.enabled is True

    assert len(await app_repo.list_monitors(app_id="checkout-api")) == 1
    await app_repo.update_monitor("mon-1", {"enabled": False, "threshold_value": 250.0})
    updated = await app_repo.get_monitor("mon-1")
    assert updated.enabled is False
    assert updated.threshold_value == 250.0
    assert await app_repo.list_monitors(app_id="checkout-api", enabled_only=True) == []

    assert await app_repo.delete_monitor("mon-1") is True
    assert await app_repo.get_monitor("mon-1") is None


@pytest.mark.asyncio
async def test_deleting_an_application_removes_its_monitors(repos):
    app_repo, _ = repos
    await _register_app(app_repo)
    await app_repo.save_monitor(_monitor())
    await app_repo.delete_application("checkout-api")
    assert await app_repo.list_monitors(app_id="checkout-api") == []


@pytest.mark.asyncio
async def test_breach_opens_an_incident_only_after_the_required_streak(
    repos, monkeypatch, tmp_path
):
    """One breach is not enough; the configured streak must be reached."""
    from tests.test_llm_schemas import VALID_ANALYSIS, FakeCompletion

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.llm.client.litellm.acompletion", FakeCompletion(json.dumps(VALID_ANALYSIS))
    )
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "reports_dir", tmp_path)

    app_repo, incident_repo = repos
    record = await _register_app(app_repo)
    await app_repo.save_monitor(_monitor(consecutive_breaches_required=2))
    for sample in _snapshots([900.0, 950.0, 1000.0]):
        await app_repo.save_probe_snapshot(sample)

    first = await evaluate_monitors_for_app(record, app_repo, incident_repo, settings=settings)
    assert first == []
    assert (await app_repo.get_monitor("mon-1")).consecutive_breaches == 1
    assert await incident_repo.get_incident(monitor_incident_id("mon-1")) is None

    second = await evaluate_monitors_for_app(record, app_repo, incident_repo, settings=settings)
    assert len(second) == 1

    incident = await incident_repo.get_incident(monitor_incident_id("mon-1"))
    assert incident is not None
    # The breach must carry real AI analysis, not just threshold arithmetic.
    assert incident.degraded is False
    assert incident.probable_cause == VALID_ANALYSIS["probable_cause"]
    assert "Checkout API" in incident.title
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_recovery_resets_the_breach_streak(repos):
    app_repo, incident_repo = repos
    record = await _register_app(app_repo)
    await app_repo.save_monitor(_monitor(consecutive_breaches_required=3))

    for sample in _snapshots([900.0, 950.0, 1000.0]):
        await app_repo.save_probe_snapshot(sample)
    await evaluate_monitors_for_app(record, app_repo, incident_repo)
    assert (await app_repo.get_monitor("mon-1")).consecutive_breaches == 1

    # Healthy samples bring the latest reading back under the limit.
    for sample in _snapshots([10.0, 10.0, 10.0], spacing=1):
        await app_repo.save_probe_snapshot(sample)
    await evaluate_monitors_for_app(record, app_repo, incident_repo)
    assert (await app_repo.get_monitor("mon-1")).consecutive_breaches == 0


def test_monitor_crud_over_http():
    with TestClient(fastapi_app) as client:
        client.post(
            "/api/v1/applications",
            json={
                "app_id": "monitor-api-app",
                "name": "Monitor API App",
                "health_url": "https://example.com/healthz",
            },
        )
        created = client.post(
            "/api/v1/applications/monitor-api-app/monitors",
            json={"name": "Slow responses", "threshold_value": 800.0},
        )
        assert created.status_code == 201
        monitor_id = created.json()["monitor_id"]
        assert created.json()["window_seconds"] == SETTINGS.monitor_default_window_seconds

        listed = client.get("/api/v1/applications/monitor-api-app/monitors")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        patched = client.patch(
            f"/api/v1/applications/monitor-api-app/monitors/{monitor_id}",
            json={"threshold_value": 400.0, "enabled": False},
        )
        assert patched.status_code == 200
        assert patched.json()["threshold_value"] == 400.0
        assert patched.json()["enabled"] is False

        evaluated = client.post(
            f"/api/v1/applications/monitor-api-app/monitors/{monitor_id}/evaluate"
        )
        assert evaluated.status_code == 200
        assert "breached" in evaluated.json()

        assert (
            client.delete(f"/api/v1/applications/monitor-api-app/monitors/{monitor_id}").status_code
            == 204
        )
        client.delete("/api/v1/applications/monitor-api-app")


def test_invalid_monitor_choices_are_rejected_with_the_allowed_values():
    with TestClient(fastapi_app) as client:
        client.post(
            "/api/v1/applications",
            json={
                "app_id": "monitor-validation-app",
                "name": "Validation App",
                "health_url": "https://example.com/healthz",
            },
        )
        resp = client.post(
            "/api/v1/applications/monitor-validation-app/monitors",
            json={"name": "Bad signal", "signal_source": "cpu_from_space"},
        )
        assert resp.status_code == 400
        assert "probe_latency" in resp.json()["detail"]
        client.delete("/api/v1/applications/monitor-validation-app")


def test_monitors_on_an_unknown_application_are_404():
    with TestClient(fastapi_app) as client:
        resp = client.post(
            "/api/v1/applications/no-such-app/monitors",
            json={"name": "Orphan monitor"},
        )
        assert resp.status_code == 404


def test_monitor_options_are_discoverable():
    with TestClient(fastapi_app) as client:
        body = client.get("/api/v1/monitors/options").json()
    assert "probe_latency" in body["signal_sources"]
    assert set(body["modes"]) == {"threshold", "anomaly"}
    assert "gt" in body["comparisons"]
