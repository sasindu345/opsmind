"""RESTful incident lifecycle management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from config.settings import get_settings
from src.infrastructure.factory import get_artifact_storage, get_incident_repository
from src.llm.schemas import IncidentStatus

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.get("", response_model=list[dict[str, Any]])
async def list_incidents_endpoint(
    service: str | None = Query(default=None, description="Filter by service name"),
    status: str | None = Query(default=None, description="Filter by incident status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """List historical and active incidents."""
    settings = get_settings()
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
) -> dict[str, Any]:
    """Get full details of a specific incident."""
    settings = get_settings()
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
) -> dict[str, str]:
    """Acknowledge an incident and transition status to ACKNOWLEDGED."""
    settings = get_settings()
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
) -> dict[str, str]:
    """Resolve an incident and record resolution timestamp."""
    settings = get_settings()
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
) -> list[dict[str, Any]]:
    """Retrieve the multi-source chronological timeline for an incident."""
    settings = get_settings()
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
) -> dict[str, str]:
    """Retrieve the report URI or presigned download link for an incident post-mortem."""
    settings = get_settings()
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


class RemediationDryRunRequest(BaseModel):
    """Payload to request a dry-run remediation plan."""

    runbook_id: str = Field(description="Runbook identifier from approved catalog")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Execution parameters")


class RemediationApproveRequest(BaseModel):
    """Payload to approve and execute a remediation action."""

    plan_id: str = Field(description="Plan ID generated during dry-run preview")
    approved_by: str = Field(description="Email or username of the approving engineer")
    reason: str = Field(default="Operator approved", description="Approval justification")


@router.post("/{incident_id}/remediation/dry-run", response_model=dict[str, Any])
async def dry_run_remediation_endpoint(
    incident_id: str,
    payload: RemediationDryRunRequest,
) -> dict[str, Any]:
    """Generate a safe, preview-only dry run plan for incident remediation."""
    from src.executor.runner import get_remediation_runner

    settings = get_settings()
    repo = get_incident_repository(settings)
    record = await repo.get_incident(incident_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    runner = get_remediation_runner(settings)
    try:
        plan = runner.create_dry_run_plan(
            incident_id=incident_id,
            runbook_id=payload.runbook_id,
            params={"service": record.service, **payload.parameters},
        )
        return {
            "plan_id": plan.plan_id,
            "incident_id": plan.incident_id,
            "runbook_id": plan.runbook_id,
            "runbook_name": plan.runbook_name,
            "risk_level": plan.risk_level,
            "blast_radius": plan.blast_radius,
            "command_preview": plan.command_preview,
            "parameters": plan.parameters,
            "created_at": plan.created_at,
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{incident_id}/remediation/approve", response_model=dict[str, Any])
async def approve_remediation_endpoint(
    incident_id: str,
    payload: RemediationApproveRequest,
) -> dict[str, Any]:
    """Execute an approved remediation plan with shell=False safety and audit logging."""
    from src.executor.runner import get_remediation_runner

    settings = get_settings()
    runner = get_remediation_runner(settings)
    plan = runner.get_plan(payload.plan_id)
    if not plan or plan.incident_id != incident_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Remediation plan {payload.plan_id} not found for incident {incident_id}",
        )

    try:
        result = await runner.execute_approved_plan(
            plan=plan,
            approved_by=payload.approved_by,
            reason=payload.reason,
        )
        return {
            "execution_id": result.execution_id,
            "plan_id": result.plan_id,
            "incident_id": result.incident_id,
            "runbook_id": result.runbook_id,
            "approved_by": result.approved_by,
            "status": result.status,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
            "executed_at": result.executed_at,
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/{incident_id}/similar", response_model=list[dict[str, Any]])
async def get_similar_incidents_endpoint(
    incident_id: str,
    top_k: int = Query(default=3, ge=1, le=10),
) -> list[dict[str, Any]]:
    """Retrieve historical incidents similar to this one via vector embeddings (RAG)."""
    from src.memory.vector_store import get_memory_store

    settings = get_settings()
    repo = get_incident_repository(settings)
    record = await repo.get_incident(incident_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    memory_store = get_memory_store(settings)
    query_text = f"{record.service} {record.title} {record.probable_cause}"
    matches = await memory_store.search(query_text=query_text, service=record.service, top_k=top_k)

    return [
        {
            "incident_id": doc.incident_id,
            "service": doc.service,
            "title": doc.title,
            "probable_cause": doc.probable_cause,
            "summary": doc.summary,
            "similarity_score": round(score, 3),
            "created_at": doc.created_at,
        }
        for doc, score in matches
    ]
