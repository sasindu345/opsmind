"""Request and response models for the ingestion API."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator


class LogBatch(BaseModel):
    """A batch of raw log lines submitted for triage."""

    service: str = Field(min_length=1, description="Service or deployment the logs came from.")
    environment: str = Field(default="production")
    logs: list[str] = Field(min_length=1, max_length=20_000)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    context: str | None = Field(
        default=None, description="Optional free-text hint, e.g. 'right after deploy a1b2c3d'."
    )
    generate_report: bool = Field(
        default=True, description="Write a Markdown post-mortem to the reports directory."
    )

    @field_validator("logs")
    @classmethod
    def _drop_blank_lines(cls, value: list[str]) -> list[str]:
        cleaned = [line for line in value if line and line.strip()]
        if not cleaned:
            raise ValueError("logs contained no non-empty lines")
        return cleaned


class QueuedIncidentResponse(BaseModel):
    """Fast-acknowledgment response for asynchronous queue ingestion."""

    status: str = "queued"
    message_id: str
    correlation_id: str
    service: str
    environment: str
    queued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApplicationCreate(BaseModel):
    """Payload to register a new application for monitoring."""

    app_id: str | None = Field(
        default=None,
        description="Optional custom identifier (e.g. 'checkout-api').",
    )
    name: str = Field(min_length=1, max_length=100, description="Application display name.")
    description: str = Field(default="", max_length=500)
    environment: str = Field(
        default="production",
        description="Environment (production, staging, dev).",
    )
    owner_team: str = Field(default="devops", description="Owning team.")
    health_url: str = Field(default="", description="HTTP/HTTPS health check endpoint.")
    probe_interval_seconds: int = Field(
        default=30,
        ge=5,
        le=3600,
        description="Probe interval in seconds.",
    )


class ApplicationUpdate(BaseModel):
    """Payload to update an existing application."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    environment: str | None = Field(default=None)
    owner_team: str | None = Field(default=None)
    health_url: str | None = Field(default=None)
    probe_interval_seconds: int | None = Field(default=None, ge=5, le=3600)
    health_status: str | None = Field(default=None)


class ApplicationResponse(BaseModel):
    """Serialized application representation."""

    app_id: str
    name: str
    description: str
    environment: str
    owner_team: str
    health_url: str
    probe_interval_seconds: int
    health_status: str
    consecutive_failures: int
    current_latency_ms: float
    uptime_24h_percent: float
    last_probe_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MetricPoint(BaseModel):
    """Aggregated latency and success metric bucket."""

    timestamp: datetime
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    p95_latency_ms: float
    success_count: int
    failure_count: int
    total_count: int
    availability_percent: float


class AvailabilitySegment(BaseModel):
    """Single time slice for segmented availability bar."""

    timestamp: datetime
    status: str  # "healthy" | "degraded" | "down" | "nodata"
    availability_percent: float
    total_count: int


class ApplicationMetricsResponse(BaseModel):
    """Metrics and availability response for an application."""

    app_id: str
    range: str
    uptime_percent: float
    avg_latency_ms: float
    p95_latency_ms: float
    error_rate_percent: float
    total_probes: int
    series: list[MetricPoint]
    availability_segments: list[AvailabilitySegment]

