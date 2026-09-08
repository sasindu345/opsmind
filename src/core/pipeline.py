"""The triage pipeline: raw logs → clusters → metrics & git correlation → LLM → post-mortem.

Kept free of FastAPI types so ChatOps handlers, CLI, and async queue workers can call
exactly the same function as the HTTP route.
"""

from __future__ import annotations

import logging
import uuid

from config.settings import Settings, get_settings
from src.api.schemas import LogBatch
from src.core.anomaly_detector import AnomalyRecord
from src.core.correlator import DeploymentRecord, IncidentCorrelator
from src.core.drain_filter import DrainFilter, compression_ratio
from src.core.post_mortem import write_post_mortem
from src.llm.client import LLMClient, LLMError, heuristic_analysis
from src.llm.prompts import build_user_prompt
from src.llm.schemas import (
    AnalysisResult,
    IncidentStatus,
    LogClusterView,
    RootCauseAnalysis,
    TimelineItemView,
)

logger = logging.getLogger(__name__)


async def analyze_logs(
    batch: LogBatch,
    *,
    client: LLMClient | None = None,
    settings: Settings | None = None,
    anomalies: list[AnomalyRecord] | None = None,
    deployments: list[DeploymentRecord] | None = None,
    rag_context: str | None = None,
    persist_incident: bool = True,
) -> AnalysisResult:
    """Run one batch of logs + telemetry through the full multi-source triage pipeline."""
    settings = settings or get_settings()
    client = client or LLMClient(settings)
    incident_id = uuid.uuid4().hex

    # 1. Drain3 Log Clustering
    clusters = DrainFilter().cluster(batch.logs)
    cluster_dicts = [c.to_prompt_dict() for c in clusters]
    reduction = compression_ratio(len(batch.logs), len(clusters))
    logger.info(
        "incident %s: %d lines → %d clusters (%.1f%% reduction)",
        incident_id[:8],
        len(batch.logs),
        len(clusters),
        reduction * 100,
    )

    # 2. Multi-Source Correlation
    correlator = IncidentCorrelator()
    corr_result = correlator.correlate(
        incident_time=batch.occurred_at,
        service=batch.service,
        log_clusters=cluster_dicts,
        anomalies=anomalies,
        deployments=deployments,
    )

    # 3. Format Prompt Blocks
    deployments_text = None
    if deployments:
        deployments_text = "\n".join(
            f"- Commit {d.commit_sha[:7]} by {d.author} at {d.timestamp.strftime('%H:%M:%S UTC')}: "
            f"{d.message} (files: {', '.join(d.changed_files[:3]) or 'none'})"
            for d in deployments
        )

    metrics_text = None
    if anomalies:
        metrics_text = "\n".join(
            f"- {a.metric_name}: {a.direction} to {a.value:.2f} "
            f"(baseline: {a.baseline_value:.2f}, score: {a.score:.2f})"
            for a in anomalies
        )

    prompt = build_user_prompt(
        service=batch.service,
        environment=batch.environment,
        occurred_at=batch.occurred_at.isoformat(),
        line_count=len(batch.logs),
        clusters=cluster_dicts,
        schema=RootCauseAnalysis.model_json_schema(),
        context=batch.context,
        deployments_text=deployments_text,
        metrics_text=metrics_text,
        rag_text=rag_context,
    )

    # 4. LLM Analysis with Fallback
    degraded = False
    try:
        analysis = await client.analyze(prompt)
    except LLMError as exc:
        logger.error("LLM analysis failed (%s) — falling back to heuristics", exc)
        analysis = heuristic_analysis(cluster_dicts, batch.service)
        degraded = True

    # Combine LLM suggested evidence with deterministic observed evidence
    combined_evidence = list(dict.fromkeys(corr_result.observed_evidence + analysis.evidence))

    timeline_views = [
        TimelineItemView(
            timestamp=t.timestamp,
            source=t.source,
            event_type=t.event_type,
            description=t.description,
        )
        for t in corr_result.timeline
    ]

    result = AnalysisResult(
        incident_id=incident_id,
        service=batch.service,
        environment=batch.environment,
        status=IncidentStatus.OPEN,
        analysis=analysis,
        clusters=[LogClusterView(**c) for c in cluster_dicts],
        observed_evidence=combined_evidence,
        inferred_correlation=corr_result.inferred_cause_summary,
        timeline=timeline_views,
        lines_ingested=len(batch.logs),
        token_reduction=reduction,
        model="" if degraded else client.model,
        degraded=degraded,
    )

    if batch.generate_report:
        result.report_path = str(write_post_mortem(result, settings))

    if persist_incident:
        try:
            from src.infrastructure.factory import get_incident_repository

            repo = get_incident_repository(settings)
            await repo.save_incident(result)
        except Exception as exc:
            logger.warning("could not persist incident to repository: %s", exc)

    return result
