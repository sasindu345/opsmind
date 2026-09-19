from datetime import UTC, datetime

import pytest

from src.core.synthetic import execute_probe, probe_incident_id
from src.core.telemetry import SQLiteTelemetryStore, TelemetrySignal, correlate_signals
from src.infrastructure.interfaces import ApplicationRecord
from src.infrastructure.local.repository import (
    SQLiteApplicationRepository,
    SQLiteIncidentRepository,
)
from tests.test_synthetic import _PublicValidator, _status_fetch


def test_correlate_signals_merges_probe_git_and_logs():
    now = datetime.now(UTC)
    signals = [
        TelemetrySignal(
            signal_id="probe-1",
            source="synthetic",
            app_id="checkout-api",
            service="checkout-api",
            environment="production",
            timestamp=now,
            level="ERROR",
            raw_message="HTTP 500",
            metadata={"http_status": 500, "latency_ms": 1200},
        ),
        TelemetrySignal(
            signal_id="git-1",
            source="git",
            app_id="checkout-api",
            service="checkout-api",
            environment="production",
            timestamp=now,
            raw_message="rollback pool size",
            metadata={"commit_sha": "abc1234def567890"},
        ),
        TelemetrySignal(
            signal_id="log-1",
            source="log",
            app_id="checkout-api",
            service="checkout-api",
            environment="production",
            timestamp=now,
            level="ERROR",
            raw_message="Database connection to db-1 timed out",
        ),
    ]
    unified = correlate_signals(signals, app_id="checkout-api", incident_time=now)
    assert unified.deployment_sha == "abc1234def567890"
    assert unified.probe_summary and "HTTP 500" in unified.probe_summary
    assert unified.log_template
    assert any("timed out" in item or "<*>" in item for item in unified.evidence)


@pytest.mark.asyncio
async def test_probe_incident_aggregates_related_signals(tmp_path):
    db = tmp_path / "unified.db"
    app_repo = SQLiteApplicationRepository(db_path=db)
    incident_repo = SQLiteIncidentRepository(db_path=db)
    store = SQLiteTelemetryStore(db)
    now = datetime.now(UTC)
    await store.save_signal(
        TelemetrySignal(
            signal_id="git-1",
            source="git",
            app_id="checkout-api",
            service="checkout-api",
            environment="production",
            timestamp=now,
            raw_message="ship checkout change",
            metadata={"commit_sha": "deadbeefcafebabe"},
        )
    )
    await store.save_signal(
        TelemetrySignal(
            signal_id="log-1",
            source="log",
            app_id="checkout-api",
            service="checkout-api",
            environment="production",
            timestamp=now,
            level="ERROR",
            raw_message="Database connection to db-1 timed out",
        )
    )
    app = ApplicationRecord(
        app_id="checkout-api",
        name="Checkout API",
        health_url="http://checkout.example/healthz",
        health_status="unknown",
    )
    await app_repo.save_application(app)
    for _ in range(2):
        app = await app_repo.get_application("checkout-api")
        await execute_probe(
            app,
            app_repo,
            incident_repo,
            validator=_PublicValidator(),
            fetch=_status_fetch(500),
            telemetry_store=store,
        )
    app = await app_repo.get_application("checkout-api")
    outcome = await execute_probe(
        app,
        app_repo,
        incident_repo,
        validator=_PublicValidator(),
        fetch=_status_fetch(500),
        telemetry_store=store,
    )
    assert outcome.incident_opened is True
    incident = await incident_repo.get_incident(probe_incident_id("checkout-api"))
    assert incident is not None
    assert incident.app_id == "checkout-api"
    assert incident.deployment_sha == "deadbeefcafebabe"
    joined = " ".join(incident.evidence_summary)
    assert "deadbee" in joined
    assert "timed out" in joined
    assert "HTTP" in joined or "probe" in joined.lower()
