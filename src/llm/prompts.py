"""Prompt templates.

Prompts consume Drain3 *templates*, anomaly detection metrics, and git deployment
metadata, never raw log lines — saving tokens and preserving high SNR.
"""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """You are OpsMind, a senior site reliability engineer performing incident triage.

You are given clustered log patterns, metric anomaly telemetry, and recent git deployment metadata.
Each log cluster is a pattern that occurred N times; placeholders like <NUM>, <IP> and <*> replace
variable parts.

Rules:
- Reason strictly from the provided evidence. Never invent log lines, metrics,
  commit SHAs, or authors.
- Clearly separate deterministic evidence from your inference.
- Prefer one specific, actionable probable cause over a list of vague possibilities.
- Set `confidence` honestly: below 0.4 when evidence is thin or ambiguous; above 0.8 only when
  log patterns directly align with metric spikes or deployment changes.
- Quote real templates or observed telemetry in `evidence`.
- Suggested fixes must be concrete and safe; mark anything that restarts, scales or rolls back
  as `risk: high`.
- Blameless: describe systems and changes, never individuals at fault.
- Respond with a single JSON object and nothing else. No markdown fences, no prose.
"""

_USER_TEMPLATE = """Service: {service}
Environment: {environment}
Time of incident: {occurred_at}
Log lines ingested: {line_count} (clustered into {cluster_count} patterns)
{context_block}
{deployments_block}
{metrics_block}
{rag_block}
Clustered log templates (most severe and frequent first):
{clusters}

Return JSON matching exactly this schema:
{schema}
"""


def build_user_prompt(
    *,
    service: str,
    environment: str,
    occurred_at: str,
    line_count: int,
    clusters: list[dict[str, Any]],
    schema: dict[str, Any],
    context: str | None = None,
    deployments_text: str | None = None,
    metrics_text: str | None = None,
    rag_text: str | None = None,
) -> str:
    context_block = f"Operator context: {context}\n" if context else ""
    deployments_block = (
        f"Recent Git Deployments/Commits:\n{deployments_text}\n" if deployments_text else ""
    )
    metrics_block = f"Observed Metric Anomalies:\n{metrics_text}\n" if metrics_text else ""
    rag_block = f"Historical Similar Incidents (RAG Memory):\n{rag_text}\n" if rag_text else ""

    rendered = "\n".join(
        f"{i}. [{c.get('level', 'INFO')}] x{c.get('occurrences', 1)}  {c.get('template', '')}\n"
        f"   sample: {c.get('sample', '')}"
        for i, c in enumerate(clusters, start=1)
    )
    return _USER_TEMPLATE.format(
        service=service,
        environment=environment,
        occurred_at=occurred_at,
        line_count=line_count,
        cluster_count=len(clusters),
        context_block=context_block,
        deployments_block=deployments_block,
        metrics_block=metrics_block,
        rag_block=rag_block,
        clusters=rendered,
        schema=json.dumps(schema, indent=2),
    )


REPAIR_PROMPT = """Your previous response did not match the required schema.

Validation error:
{error}

Return the corrected JSON object only — no explanation, no markdown fences.
"""
