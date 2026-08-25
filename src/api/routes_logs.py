"""Log ingestion and analysis endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from src.api.schemas import LogBatch
from src.core.pipeline import analyze_logs
from src.llm.schemas import AnalysisResult

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.post("/analyze/logs", response_model=AnalysisResult)
async def analyze_logs_endpoint(batch: LogBatch) -> AnalysisResult:
    """Cluster raw logs, run root-cause analysis and emit a Markdown post-mortem.

    Never fails on LLM outage: the response is marked ``degraded`` and carries a
    heuristic analysis instead.
    """
    return await analyze_logs(batch)
