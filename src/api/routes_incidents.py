"""RESTful incident lifecycle management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from config.settings import Settings, get_settings
from src.infrastructure.factory import get_artifact_storage, get_incident_repository
from src.llm.schemas import IncidentStatus

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.get("", response_model=list[dict[str, Any]])
async def list_incidents_endpoint(
    service: str | None = Query(default=None, description="Filter by service name"),
    status: str | None = Query(default=None, description="Filter by incident status"),
    limit: int = Query(default=50, ge=1, le=200),
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """List historical and active incidents."""
    settings = settings or get_settings()
    repo = get_incident_repository(settings)
    records = await repo.list_incidents(service=service, status=status, limit=limit)
    return [
        {
            "incident_id": r.incident_id,
            "service": r.service,
            "environment": r.environment,
            "severity": r.severity,
            "status": r.status,
            "title": r.title,
            "probable_cause": r.probable_cause,
            "confidence": r.confidence,
            "created_at": r.created_at.isoformat(),
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            "report_uri": r.report_uri,
        }
        for r in records
    ]


@router.get("/{incident_id}", response_model=dict[str, Any])
async def get_incident_endpoint(
    incident_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Get full details of a specific incident."""
    settings = settings or get_settings()
    repo = get_incident_repository(settings)
    record = await repo.get_incident(incident_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )
    return {
        "incident_id": record.incident_id,
        "service": record.service,
        "environment": record.environment,
        "severity": record.severity,
        "status": record.status,
        "title": record.title,
        "probable_cause": record.probable_cause,
        "confidence": record.confidence,
        "model": record.model,
        "degraded": record.degraded,
        "created_at": record.created_at.isoformat(),
        "resolved_at": record.resolved_at.isoformat() if record.resolved_at else None,
        "evidence": record.evidence_summary,
        "timeline": record.timeline_json,
        "report_uri": record.report_uri,
        "artifact_uri": record.artifact_uri,
    }


@router.post("/{incident_id}/acknowledge", response_model=dict[str, str])
async def acknowledge_incident_endpoint(
    incident_id: str,
    settings: Settings | None = None,
) -> dict[str, str]:
    """Acknowledge an incident and transition status to ACKNOWLEDGED."""
    settings = settings or get_settings()
    repo = get_incident_repository(settings)
    record = await repo.get_incident(incident_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    await repo.update_status(incident_id, IncidentStatus.ACKNOWLEDGED)
    return {"incident_id": incident_id, "status": "acknowledged"}


@router.post("/{incident_id}/resolve", response_model=dict[str, str])
async def resolve_incident_endpoint(
    incident_id: str,
    settings: Settings | None = None,
) -> dict[str, str]:
    """Resolve an incident and record resolution timestamp."""
    settings = settings or get_settings()
    repo = get_incident_repository(settings)
    record = await repo.get_incident(incident_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    await repo.update_status(incident_id, IncidentStatus.RESOLVED)
    return {"incident_id": incident_id, "status": "resolved"}


@router.get("/{incident_id}/timeline", response_model=list[dict[str, Any]])
async def get_incident_timeline_endpoint(
    incident_id: str,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Retrieve the multi-source chronological timeline for an incident."""
    settings = settings or get_settings()
    repo = get_incident_repository(settings)
    record = await repo.get_incident(incident_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )
    return record.timeline_json


@router.post("/{incident_id}/postmortem", response_model=dict[str, str])
async def get_incident_postmortem_endpoint(
    incident_id: str,
    settings: Settings | None = None,
) -> dict[str, str]:
    """Retrieve the report URI or presigned download link for an incident post-mortem."""
    settings = settings or get_settings()
    repo = get_incident_repository(settings)
    storage = get_artifact_storage(settings)

    record = await repo.get_incident(incident_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    report_uri = record.report_uri or f"reports/incident-{incident_id}.md"
    url = await storage.generate_presigned_url(report_uri)
    return {"incident_id": incident_id, "report_uri": report_uri, "access_url": url}
