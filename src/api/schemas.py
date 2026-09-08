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
