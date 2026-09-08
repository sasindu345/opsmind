"""Log ingestion and analysis endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.api.schemas import LogBatch, QueuedIncidentResponse
from src.core.pipeline import analyze_logs
from src.core.worker import IncidentMessage, get_local_queue
from src.llm.schemas import AnalysisResult

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.post("/analyze/logs", response_model=AnalysisResult)
async def analyze_logs_endpoint(batch: LogBatch) -> AnalysisResult:
    """Cluster raw logs, run root-cause analysis and emit a Markdown post-mortem synchronously.

    Never fails on LLM outage: the response is marked ``degraded`` and carries a
    heuristic analysis instead.
    """
    return await analyze_logs(batch)


@router.post(
    "/analyze/logs/async",
    response_model=QueuedIncidentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_logs_async_endpoint(batch: LogBatch) -> QueuedIncidentResponse:
    """Acknowledge immediately (<50ms) and enqueue incident for asynchronous worker processing."""
    message_id = uuid.uuid4().hex
    correlation_id = uuid.uuid4().hex
    queue = get_local_queue()

    msg = IncidentMessage(
        message_id=message_id,
        correlation_id=correlation_id,
        service=batch.service,
        environment=batch.environment,
        event_type="logs",
        payload={
            "logs": batch.logs,
            "context": batch.context,
            "generate_report": batch.generate_report,
        },
        created_at=batch.occurred_at,
    )

    await queue.enqueue(msg)

    return QueuedIncidentResponse(
        status="queued",
        message_id=message_id,
        correlation_id=correlation_id,
        service=batch.service,
        environment=batch.environment,
        queued_at=batch.occurred_at,
    )
