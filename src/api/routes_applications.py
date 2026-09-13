"""Application management and health inspection endpoints."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from config.settings import get_settings
from src.api.schemas import ApplicationCreate, ApplicationResponse, ApplicationUpdate
from src.infrastructure.factory import get_application_repository
from src.infrastructure.interfaces import ApplicationRecord, ApplicationRepository

logger = logging.getLogger("opsmind.api.applications")

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])


def _get_repo() -> ApplicationRepository:
    return get_application_repository(get_settings())


RepoDep = Annotated[ApplicationRepository, Depends(_get_repo)]


def _slugify(name: str) -> str:
    """Convert display name to a URL/ID friendly slug."""
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower())
    return clean.strip("-") or str(uuid.uuid4())[:8]


def _record_to_response(app: ApplicationRecord) -> ApplicationResponse:
    return ApplicationResponse(
        app_id=app.app_id,
        name=app.name,
        description=app.description,
        environment=app.environment,
        owner_team=app.owner_team,
        health_url=app.health_url,
        probe_interval_seconds=app.probe_interval_seconds,
        health_status=app.health_status,
        consecutive_failures=app.consecutive_failures,
        current_latency_ms=app.current_latency_ms,
        uptime_24h_percent=app.uptime_24h_percent,
        last_probe_at=app.last_probe_at,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ApplicationCreate,
    repo: RepoDep,
) -> ApplicationResponse:
    """Register a new application for monitoring."""
    app_id = payload.app_id or _slugify(payload.name)

    existing = await repo.get_application(app_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Application with ID '{app_id}' already exists",
        )

    record = ApplicationRecord(
        app_id=app_id,
        name=payload.name,
        description=payload.description,
        environment=payload.environment.lower(),
        owner_team=payload.owner_team,
        health_url=payload.health_url.strip(),
        probe_interval_seconds=payload.probe_interval_seconds,
        health_status="healthy" if not payload.health_url else "unknown",
        consecutive_failures=0,
        current_latency_ms=0.0,
        uptime_24h_percent=100.0,
        last_probe_at=None,
    )

    await repo.save_application(record)
    logger.info("created application entity: %s (%s)", record.app_id, record.name)
    return _record_to_response(record)


@router.get("", response_model=list[ApplicationResponse])
async def list_applications(
    repo: RepoDep,
    environment: str | None = Query(default=None, description="Filter by environment"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ApplicationResponse]:
    """List all registered applications."""
    apps = await repo.list_applications(environment=environment, limit=limit)
    return [_record_to_response(app) for app in apps]


@router.get("/{app_id}", response_model=ApplicationResponse)
async def get_application(
    app_id: str,
    repo: RepoDep,
) -> ApplicationResponse:
    """Retrieve application details by ID."""
    app = await repo.get_application(app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    return _record_to_response(app)


@router.patch("/{app_id}", response_model=ApplicationResponse)
async def update_application(
    app_id: str,
    payload: ApplicationUpdate,
    repo: RepoDep,
) -> ApplicationResponse:
    """Update application attributes."""
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        app = await repo.get_application(app_id)
        if not app:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Application '{app_id}' not found",
            )
        return _record_to_response(app)

    updated = await repo.update_application(app_id, updates)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    return _record_to_response(updated)


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    app_id: str,
    repo: RepoDep,
) -> Response:
    """Deregister an application from monitoring."""
    success = await repo.delete_application(app_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{app_id}/probe", response_model=dict[str, object])
async def probe_application_now(
    app_id: str,
    repo: RepoDep,
) -> dict[str, object]:
    """Execute an immediate manual health check against the application health URL."""
    app = await repo.get_application(app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )

    if not app.health_url:
        return {
            "app_id": app_id,
            "status": "skipped",
            "message": "Application has no configured health_url",
            "latency_ms": 0.0,
        }

    start = datetime.now(UTC)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(app.health_url)
            latency_ms = (datetime.now(UTC) - start).total_seconds() * 1000.0
            is_success = 200 <= resp.status_code < 400
            new_status = "healthy" if is_success else "critical"
            consecutive = 0 if is_success else app.consecutive_failures + 1

            await repo.update_application(
                app_id,
                {
                    "health_status": new_status,
                    "current_latency_ms": round(latency_ms, 2),
                    "consecutive_failures": consecutive,
                    "last_probe_at": datetime.now(UTC),
                },
            )

            return {
                "app_id": app_id,
                "status": new_status,
                "http_status": resp.status_code,
                "latency_ms": round(latency_ms, 2),
                "is_success": is_success,
            }
    except Exception as exc:
        latency_ms = (datetime.now(UTC) - start).total_seconds() * 1000.0
        consecutive = app.consecutive_failures + 1
        await repo.update_application(
            app_id,
            {
                "health_status": "critical",
                "current_latency_ms": round(latency_ms, 2),
                "consecutive_failures": consecutive,
                "last_probe_at": datetime.now(UTC),
            },
        )
        return {
            "app_id": app_id,
            "status": "critical",
            "error": str(exc),
            "latency_ms": round(latency_ms, 2),
            "is_success": False,
        }
