"""The triage pipeline: raw logs → clusters → LLM → post-mortem.

Kept free of FastAPI types so Phase 2's Slack handler and CLI can call exactly
the same function as the HTTP route.
"""

from __future__ import annotations

import logging
import uuid

from config.settings import Settings, get_settings
from src.api.schemas import LogBatch
from src.core.drain_filter import DrainFilter, compression_ratio
from src.core.post_mortem import write_post_mortem
from src.llm.client import LLMClient, LLMError, heuristic_analysis
from src.llm.prompts import build_user_prompt
from src.llm.schemas import AnalysisResult, LogClusterView, RootCauseAnalysis

logger = logging.getLogger(__name__)


async def analyze_logs(
    batch: LogBatch,
    *,
    client: LLMClient | None = None,
    settings: Settings | None = None,
) -> AnalysisResult:
    """Run one batch of logs through the full Phase 1 pipeline."""
    settings = settings or get_settings()
    client = client or LLMClient(settings)
    incident_id = uuid.uuid4().hex

    clusters = DrainFilter().cluster(batch.logs)
    cluster_dicts = [c.to_prompt_dict() for c in clusters]
    logger.info(
        "incident %s: %d lines → %d clusters (%.1f%% reduction)",
        incident_id[:8],
        len(batch.logs),
        len(clusters),
        compression_ratio(len(batch.logs), len(clusters)) * 100,
    )

    prompt = build_user_prompt(
        service=batch.service,
        environment=batch.environment,
        occurred_at=batch.occurred_at.isoformat(),
        line_count=len(batch.logs),
        clusters=cluster_dicts,
        schema=RootCauseAnalysis.model_json_schema(),
        context=batch.context,
    )

    degraded = False
    try:
        analysis = await client.analyze(prompt)
    except LLMError as exc:
        logger.error("LLM analysis failed (%s) — falling back to heuristics", exc)
        analysis = heuristic_analysis(cluster_dicts, batch.service)
        degraded = True

    result = AnalysisResult(
        incident_id=incident_id,
        service=batch.service,
        environment=batch.environment,
        analysis=analysis,
        clusters=[LogClusterView(**c) for c in cluster_dicts],
        lines_ingested=len(batch.logs),
        token_reduction=compression_ratio(len(batch.logs), len(clusters)),
        model="" if degraded else client.model,
        degraded=degraded,
    )

    if batch.generate_report:
        result.report_path = str(write_post_mortem(result, settings))

    return result
