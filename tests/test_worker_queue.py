import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from config.settings import get_settings
from src.core.worker import IncidentMessage, IncidentWorker, LocalIncidentQueue
from src.main import app
from tests.test_llm_schemas import VALID_ANALYSIS, FakeCompletion


def test_message_envelope_serialization():
    msg = IncidentMessage(
        message_id="msg-123",
        correlation_id="corr-456",
        service="checkout",
        environment="production",
        event_type="logs",
        payload={"logs": ["line 1", "line 2"]},
    )
    assert msg.deduplication_id != ""
    data = msg.to_dict()
    restored = IncidentMessage.from_dict(data)
    assert restored.message_id == "msg-123"
    assert restored.service == "checkout"
    assert restored.deduplication_id == msg.deduplication_id


@pytest.mark.asyncio
async def test_worker_processes_message_successfully(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.llm.client.litellm.acompletion", FakeCompletion(json.dumps(VALID_ANALYSIS))
    )
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "reports_dir", tmp_path)

    queue = LocalIncidentQueue()
    worker = IncidentWorker(queue=queue, settings=settings)

    msg = IncidentMessage(
        message_id="msg-1",
        correlation_id="corr-1",
        service="checkout",
        environment="production",
        event_type="logs",
        payload={"logs": ["ERROR database connection timed out"]},
    )
    await queue.enqueue(msg)

    result = await worker.run_once()
    assert result is not None
    assert result.service == "checkout"
    assert worker.processed_count == 1
    assert queue.is_duplicate(msg.deduplication_id)
    assert len(queue.dlq) == 0


@pytest.mark.asyncio
async def test_worker_moves_poison_pill_to_dlq_after_max_retries(monkeypatch):
    queue = LocalIncidentQueue()
    worker = IncidentWorker(queue=queue)

    msg = IncidentMessage(
        message_id="poison-1",
        correlation_id="corr-p",
        service="broken-svc",
        environment="staging",
        event_type="logs",
        payload={"logs": ["corrupt log"]},
        retry_count=3,
        max_retries=3,
    )
    await queue.enqueue(msg)

    # Mock process_message to raise an error
    monkeypatch.setattr(
        worker,
        "process_message",
        MagicMock(side_effect=RuntimeError("Fatal deserialization error")),
    )

    result = await worker.run_once()
    assert result is None
    assert len(queue.dlq) == 1
    assert queue.dlq[0].message_id == "poison-1"


@pytest.mark.asyncio
async def test_worker_skips_duplicate_messages(monkeypatch):
    queue = LocalIncidentQueue()
    worker = IncidentWorker(queue=queue)

    msg = IncidentMessage(
        message_id="dup-1",
        correlation_id="corr-dup",
        service="checkout",
        environment="production",
        event_type="logs",
        payload={"logs": ["ERROR duplicate message"]},
    )
    queue.processed_dedup_ids.add(msg.deduplication_id)

    result = await worker.process_message(msg)
    assert result is None  # Skipped


def test_async_endpoint_returns_202_accepted():
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/analyze/logs/async",
            json={
                "service": "payments",
                "environment": "production",
                "logs": ["2026-09-06 ERROR Payment gateway 504 gateway timeout"],
            },
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["service"] == "payments"
    assert "message_id" in body
    assert "correlation_id" in body
