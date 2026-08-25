"""Prompt templates.

Prompts consume Drain3 *templates*, never raw log lines — that is where the
token savings come from.
"""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """You are OpsMind, a senior site reliability engineer performing incident triage.

You are given clustered log templates from one service. Each cluster is a pattern
that occurred N times; placeholders like <NUM>, <IP> and <*> replace variable parts.

Rules:
- Reason only from the evidence given. Never invent log lines, metrics or commit SHAs.
- Prefer one specific probable cause over a list of possibilities.
- Set `confidence` honestly: below 0.4 when the logs are thin or ambiguous.
- Quote real templates in `evidence`.
- Suggested fixes must be concrete and safe; mark anything that restarts, scales
  or rolls back as `risk: high`.
- Blameless: describe systems and changes, never individuals at fault.
- Respond with a single JSON object and nothing else. No markdown fences, no prose.
"""

_USER_TEMPLATE = """Service: {service}
Environment: {environment}
Time of incident: {occurred_at}
Log lines ingested: {line_count} (clustered into {cluster_count} patterns)
{context_block}
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
) -> str:
    context_block = f"Operator context: {context}\n" if context else ""
    rendered = "\n".join(
        f"{i}. [{c['level']}] x{c['occurrences']}  {c['template']}\n   sample: {c['sample']}"
        for i, c in enumerate(clusters, start=1)
    )
    return _USER_TEMPLATE.format(
        service=service,
        environment=environment,
        occurred_at=occurred_at,
        line_count=line_count,
        cluster_count=len(clusters),
        context_block=context_block,
        clusters=rendered,
        schema=json.dumps(schema, indent=2),
    )


REPAIR_PROMPT = """Your previous response did not match the required schema.

Validation error:
{error}

Return the corrected JSON object only — no explanation, no markdown fences.
"""
