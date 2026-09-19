"""Infrastructure provider interfaces and abstraction layer.

Decouples core business logic from AWS SDK (boto3) and local storage details.
Allows seamless switching between Local Mode (SQLite, filesystem, in-memory)
and AWS Mode (DynamoDB, S3, EventBridge, Secrets Manager).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from src.llm.schemas import AnalysisResult, IncidentStatus


@dataclass
class IncidentRecord:
    """Standard incident representation stored in repository."""

    incident_id: str
    service: str
    environment: str
    severity: str
    status: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    title: str = ""
    probable_cause: str = ""
    confidence: float = 0.0
    model: str = ""
    degraded: bool = False
    app_id: str | None = None
    deployment_sha: str | None = None
    deployment_author: str | None = None
    evidence_summary: list[str] = field(default_factory=list)
    report_uri: str | None = None
    artifact_uri: str | None = None
    timeline_json: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_analysis_result(cls, result: AnalysisResult) -> IncidentRecord:
        return cls(
            incident_id=result.incident_id,
            service=result.service,
            environment=result.environment,
            app_id=result.app_id,
            deployment_sha=result.deployment_sha,
            severity=result.analysis.severity.value,
            status=result.status.value,
            created_at=result.created_at,
            resolved_at=result.resolved_at,
            title=result.analysis.title,
            probable_cause=result.analysis.probable_cause,
            confidence=result.analysis.confidence,
            model=result.model,
            degraded=result.degraded,
            evidence_summary=result.observed_evidence or result.analysis.evidence,
            report_uri=result.report_path,
            artifact_uri=result.artifact_uri,
            timeline_json=[
                {
                    "timestamp": t.timestamp.isoformat(),
                    "source": t.source,
                    "event_type": t.event_type,
                    "description": t.description,
                }
                for t in result.timeline
            ],
        )


@dataclass
class ApplicationRecord:
    """Application entity representation stored in repository."""

    app_id: str
    name: str
    description: str = ""
    environment: str = "production"
    owner_team: str = "devops"
    health_url: str = ""
    probe_interval_seconds: int = 30
    health_status: str = "healthy"
    consecutive_failures: int = 0
    current_latency_ms: float = 0.0
    uptime_24h_percent: float = 100.0
    last_probe_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class HealthProbeSnapshot:
    """One synthetic health-check sample for an application."""

    probe_id: str
    app_id: str
    timestamp: datetime
    http_status: int
    latency_ms: float
    is_success: bool
    error_message: str | None = None
    resolved_ip: str | None = None


class ApplicationRepository(Protocol):
    """Abstract application repository protocol."""

    async def save_application(self, app: ApplicationRecord) -> str:
        """Persist or update an application and return app_id."""
        ...

    async def get_application(self, app_id: str) -> ApplicationRecord | None:
        """Retrieve an application by ID."""
        ...

    async def list_applications(
        self,
        environment: str | None = None,
        limit: int = 100,
    ) -> list[ApplicationRecord]:
        """List applications with optional environment filtering."""
        ...

    async def update_application(
        self,
        app_id: str,
        updates: dict[str, Any],
    ) -> ApplicationRecord | None:
        """Update specific fields of an application."""
        ...

    async def delete_application(self, app_id: str) -> bool:
        """Delete an application by ID."""
        ...

    async def save_probe_snapshot(self, snapshot: HealthProbeSnapshot) -> str:
        """Persist one health probe sample and return probe_id."""
        ...

    async def list_probe_snapshots(
        self,
        app_id: str,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[HealthProbeSnapshot]:
        """Return recent probe samples for an application, newest first."""
        ...


class IncidentRepository(Protocol):
    """Abstract incident repository protocol."""

    async def save_incident(self, result: AnalysisResult) -> str:
        """Persist incident analysis result and return incident_id."""
        ...

    async def get_incident(self, incident_id: str) -> IncidentRecord | None:
        """Retrieve an incident by ID."""
        ...

    async def list_incidents(
        self,
        service: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[IncidentRecord]:
        """List incidents with optional filtering."""
        ...

    async def update_status(self, incident_id: str, new_status: IncidentStatus) -> bool:
        """Update the status of an incident."""
        ...


class ArtifactStorage(Protocol):
    """Abstract long-term artifact storage protocol (Reports, Evidence, Raw Logs)."""

    async def store_artifact(
        self,
        key: str,
        content: str | bytes,
        content_type: str = "text/markdown",
    ) -> str:
        """Store an artifact and return its URI."""
        ...

    async def get_artifact(self, key: str) -> str | bytes:
        """Retrieve an artifact by key."""
        ...

    async def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a URL or path to access the artifact."""
        ...


class EventPublisher(Protocol):
    """Abstract event publishing protocol."""

    async def publish_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        source: str = "opsmind",
    ) -> str:
        """Publish an event and return event/message ID."""
        ...


class SecretManager(Protocol):
    """Abstract secret retrieval protocol."""

    async def get_secret(self, secret_name: str) -> str | None:
        """Retrieve a secret by name."""
        ...
