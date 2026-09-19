"""Slack Block Kit builder for interactive incident notification cards."""

from __future__ import annotations

from typing import Any

from src.infrastructure.interfaces import IncidentRecord
from src.llm.schemas import AnalysisResult


def _severity_badge(severity_str: str) -> str:
    sev = severity_str.lower()
    badges = {
        "critical": "🔴 *CRITICAL*",
        "high": "🟠 *HIGH*",
        "medium": "🟡 *MEDIUM*",
        "low": "🔵 *LOW*",
        "info": "⚪ *INFO*",
    }
    return badges.get(sev, "🟡 *MEDIUM*")


def build_incident_card(
    incident: AnalysisResult | IncidentRecord,
    base_url: str = "http://localhost:8000",
) -> list[dict[str, Any]]:
    """Construct an interactive Slack Block Kit message payload."""
    if isinstance(incident, AnalysisResult):
        inc_id = incident.incident_id
        service = incident.service
        environment = incident.environment
        severity = incident.analysis.severity.value
        status = incident.status.value
        title = incident.analysis.title
        probable_cause = incident.analysis.probable_cause
        confidence = incident.analysis.confidence
        evidence = incident.observed_evidence or incident.analysis.evidence
        fixes = incident.analysis.suggested_fixes
    else:
        inc_id = incident.incident_id
        service = incident.service
        environment = incident.environment
        severity = incident.severity
        status = incident.status
        title = incident.title
        probable_cause = incident.probable_cause
        confidence = incident.confidence
        evidence = incident.evidence_summary
        fixes = []

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🚨 OpsMind Incident: {title[:140]}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Severity:*\n{_severity_badge(severity)}"},
                {"type": "mrkdwn", "text": f"*Status:*\n`{status.upper()}`"},
                {"type": "mrkdwn", "text": f"*Service:*\n`{service}` ({environment})"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n`{int(confidence * 100)}%`"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Probable Root Cause:*\n>{probable_cause}",
            },
        },
    ]

    # Add evidence snippet
    if evidence:
        evidence_text = "\n".join(f"• {e[:120]}" for e in evidence[:3])
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Key Evidence:*\n{evidence_text}",
                },
            }
        )

    # Add suggested remediation
    if fixes:
        top_fix = fixes[0]
        cmd_text = f"\n```{top_fix.command}```" if top_fix.command else ""
        fix_desc = (
            f"*Suggested Remediation:*\n*{top_fix.title}* ({top_fix.risk.value})\n"
            f"{top_fix.description}{cmd_text}"
        )
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": fix_desc,
                },
            }
        )

    # Interactive Action Buttons
    blocks.append(
        {
            "type": "actions",
            "block_id": f"incident_actions_{inc_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Acknowledge", "emoji": True},
                    "style": "primary",
                    "action_id": "ack_incident",
                    "value": inc_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔍 Explain & Timeline", "emoji": True},
                    "action_id": "explain_incident",
                    "value": inc_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "⚡ Remediate", "emoji": True},
                    "style": "danger",
                    "action_id": "remediate_incident",
                    "value": inc_id,
                },
            ],
        }
    )

    blocks.append({"type": "divider"})
    return blocks
