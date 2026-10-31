"""Regression tests for the asynchronous incident path.

Each test here covers a defect that shipped silently because nothing exercised
the wiring between ingestion, the queue, the worker, and the correlator.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from config.settings import Settings, get_settings
from src.core.telemetry import git_signal_id
from src.core.worker import (
    IncidentMessage,
    IncidentWorker,
    LocalIncidentQueue,
    _rebuild_anomalies,
    _rebuild_deployments,
)


def test_worker_builds_without_an_explicit_queue():
    """IncidentWorker() read settings.is_aws, which did not exist.

    The CLI worker command constructs the worker exactly this way, so it raised
    AttributeError on launch while every test injected a queue and passed.
    """
    worker = IncidentWorker()
    assert isinstance(worker.queue, LocalIncidentQueue)


def test_local_mode_never_selects_the_sqs_queue():
    settings = Settings(deployment_mode="local", sqs_queue_url="https://sqs.example/queue")
    assert settings.is_aws is False
    assert isinstance(IncidentWorker(settings=settings).queue, LocalIncidentQueue)


def test_deployments_are_rebuilt_from_a_queue_payload():
    """The worker dropped deployment payloads into a `pass` branch.

    Without reconstruction the correlator never sees the commit a webhook
    reported, so an incident can never be attributed to a deployment.
    """
    raw = [
        {
            "commit_sha": "a1b2c3d4",
            "author": "dev",
            "service": "checkout-api",
            "environment": "production",
            "message": "bump pool size",
            "changed_files": ["app/db.py"],
        }
    ]
    records = _rebuild_deployments(raw, "fallback-svc", "staging", datetime.now(UTC))
    assert len(records) == 1
    assert records[0].commit_sha == "a1b2c3d4"
    assert records[0].service == "checkout-api"
    assert records[0].changed_files == ["app/db.py"]


def test_deployment_rebuild_skips_entries_without_a_commit():
    now = datetime.now(UTC)
    assert _rebuild_deployments([{"author": "dev"}], "svc", "production", now) == []
    assert _rebuild_deployments("not-a-list", "svc", "production", now) == []
    assert _rebuild_deployments(None, "svc", "production", now) == []


def test_deployment_rebuild_falls_back_to_message_scope():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    records = _rebuild_deployments([{"commit_sha": "ff00"}], "svc-from-msg", "staging", now)
    assert records[0].service == "svc-from-msg"
    assert records[0].environment == "staging"
    assert records[0].timestamp == now


def test_anomalies_are_rebuilt_and_malformed_entries_discarded():
    now = datetime.now(UTC)
    records = _rebuild_anomalies(
        [
            {
                "metric_name": "cpu_percent",
                "value": 96.5,
                "baseline_value": 20.0,
                "threshold_value": 80.0,
                "score": 4.1,
                "method": "zscore",
                "direction": "spike",
            },
            {"metric_name": "broken"},
        ],
        now,
    )
    assert len(records) == 1
    assert records[0].metric_name == "cpu_percent"
    assert records[0].value == 96.5
    assert records[0].method.value == "zscore"


def test_anomaly_rebuild_tolerates_an_unknown_method():
    records = _rebuild_anomalies(
        [{"metric_name": "latency_ms", "value": 1.0, "method": "not-a-method"}],
        datetime.now(UTC),
    )
    assert records[0].method.value == "zscore"


def test_git_signal_id_is_deterministic_per_commit():
    """Webhook redelivery used a random UUID and duplicated telemetry rows."""
    first = git_signal_id("sasindu345", "opsmind", "a1b2c3d")
    second = git_signal_id("sasindu345", "opsmind", "a1b2c3d")
    assert first == second
    assert first != git_signal_id("sasindu345", "opsmind", "different")
    assert first != git_signal_id("other", "opsmind", "a1b2c3d")


@pytest.mark.asyncio
async def test_queued_message_reaches_the_correlator_with_its_deployment(monkeypatch, tmp_path):
    """End-to-end: an ingested event carrying a commit produces an incident."""
    from tests.test_llm_schemas import VALID_ANALYSIS, FakeCompletion

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.llm.client.litellm.acompletion", FakeCompletion(json.dumps(VALID_ANALYSIS))
    )
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "reports_dir", tmp_path)

    queue = LocalIncidentQueue()
    worker = IncidentWorker(queue=queue, settings=settings)
    await queue.enqueue(
        IncidentMessage(
            message_id="msg-git",
            correlation_id="corr-git",
            service="checkout-api",
            environment="production",
            event_type="github",
            payload={
                "logs": ["ERROR connection pool exhausted"],
                "deployments": [
                    {
                        "commit_sha": "deadbeef",
                        "author": "dev",
                        "service": "checkout-api",
                        "environment": "production",
                        "message": "reduce pool size",
                        "changed_files": ["app/db.py"],
                    }
                ],
            },
        )
    )

    result = await worker.run_once()
    assert result is not None
    assert result.service == "checkout-api"
    assert worker.processed_count == 1
    get_settings.cache_clear()
