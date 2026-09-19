"""Structured LLM output contracts.

The model is required to return JSON matching ``RootCauseAnalysis``. Anything
that fails validation is retried once with the validation error fed back; see
``src.llm.client``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def emoji(self) -> str:
        return {
            Severity.CRITICAL: "🔴",
            Severity.HIGH: "🟠",
            Severity.MEDIUM: "🟡",
            Severity.LOW: "🔵",
            Severity.INFO: "⚪",
        }[self]


class IncidentStatus(StrEnum):
    DETECTED = "detected"
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    REMEDIATING = "remediating"
    REMEDIATION_PROPOSED = "remediation_proposed"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    REMEDIATION_EXECUTING = "remediation_executing"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    FAILED = "failed"
    CLOSED = "closed"


class SuggestedFix(BaseModel):
    title: str = Field(description="Short imperative action, e.g. 'Rollback deployment'.")
    description: str = Field(description="What to do and why it addresses the cause.")
    command: str | None = Field(
        default=None,
        description="Shell/kubectl command, if one applies. Never executed without validation.",
    )
    risk: Severity = Field(
        default=Severity.MEDIUM, description="Blast radius of applying this fix."
    )
    runbook_id: str | None = Field(
        default=None,
        description="Predefined safe runbook identifier, e.g. 'rollback-deployment'.",
    )


class RootCauseAnalysis(BaseModel):
    """The LLM's verdict on one incident."""

    title: str = Field(description="One-line incident headline.")
    summary: str = Field(description="Two or three sentences describing what happened.")
    probable_cause: str = Field(description="The single most likely root cause.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the probable cause.")
    severity: Severity = Severity.MEDIUM
    affected_services: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(
        default_factory=list,
        description="Log templates, metrics or git facts supporting the conclusion.",
    )
    suggested_fixes: list[SuggestedFix] = Field(default_factory=list)


class LogClusterView(BaseModel):
    """A Drain3 cluster as surfaced in API responses."""

    template: str
    occurrences: int
    level: str
    sample: str


class TimelineItemView(BaseModel):
    """Timeline event in API response."""

    timestamp: datetime
    source: str
    event_type: str
    description: str


class AnalysisResult(BaseModel):
    """Full response of the analysis pipeline."""

    incident_id: str
    service: str
    environment: str
    status: IncidentStatus = IncidentStatus.OPEN
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    analysis: RootCauseAnalysis
    clusters: list[LogClusterView] = Field(default_factory=list)
    observed_evidence: list[str] = Field(default_factory=list)
    inferred_correlation: str | None = None
    timeline: list[TimelineItemView] = Field(default_factory=list)
    lines_ingested: int = 0
    token_reduction: float = Field(
        default=0.0, description="Fraction of log lines removed by clustering (0.0–1.0)."
    )
    model: str = ""
    degraded: bool = Field(
        default=False, description="True when the LLM failed and a heuristic report was used."
    )
    report_path: str | None = None
    artifact_uri: str | None = None
    app_id: str | None = None
    deployment_sha: str | None = None
