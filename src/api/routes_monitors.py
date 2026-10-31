"""Metric monitor configuration endpoints.

Lets a user decide what to watch on an application without editing any
configuration file, scoped to signals OpsMind already measures itself.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from config.settings import get_settings
from src.api.security import require_api_key
from src.infrastructure.factory import get_application_repository
from src.infrastructure.interfaces import (
    ANOMALY_METHODS,
    COMPARISONS,
    MONITOR_MODES,
    SIGNAL_SOURCES,
    ApplicationRepository,
    MetricMonitorRecord,
)

router = APIRouter(prefix="/api/v1/applications", tags=["monitors"])


def _repo() -> ApplicationRepository:
    # Must take no arguments: FastAPI would otherwise treat a parameter here as
    # a request field and reject every call with a 422.
    return get_application_repository(get_settings())


RepoDep = Annotated[ApplicationRepository, Depends(_repo)]


class MonitorCreate(BaseModel):
    """A monitor as a user configures it."""

    name: str = Field(min_length=1, max_length=120)
    signal_source: str = Field(default="probe_latency")
    mode: str = Field(default="threshold")
    comparison: str = Field(default="gt")
    threshold_value: float = Field(default=0.0)
    anomaly_method: str = Field(default="zscore")
    window_seconds: int | None = Field(default=None, ge=60, le=86_400)
    min_samples: int | None = Field(default=None, ge=1, le=1000)
    consecutive_breaches_required: int = Field(default=2, ge=1, le=20)
    severity: str = Field(default="HIGH")
    enabled: bool = Field(default=True)


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    signal_source: str | None = None
    mode: str | None = None
    comparison: str | None = None
    threshold_value: float | None = None
    anomaly_method: str | None = None
    window_seconds: int | None = Field(default=None, ge=60, le=86_400)
    min_samples: int | None = Field(default=None, ge=1, le=1000)
    consecutive_breaches_required: int | None = Field(default=None, ge=1, le=20)
    severity: str | None = None
    enabled: bool | None = None


class MonitorResponse(BaseModel):
    monitor_id: str
    app_id: str
    name: str
    signal_source: str
    mode: str
    comparison: str
    threshold_value: float
    anomaly_method: str
    window_seconds: int
    min_samples: int
    consecutive_breaches_required: int
    severity: str
    enabled: bool
    consecutive_breaches: int
    last_evaluated_at: str | None
    last_breached_at: str | None
    created_at: str

    @classmethod
    def from_record(cls, record: MetricMonitorRecord) -> MonitorResponse:
        return cls(
            monitor_id=record.monitor_id,
            app_id=record.app_id,
            name=record.name,
            signal_source=record.signal_source,
            mode=record.mode,
            comparison=record.comparison,
            threshold_value=record.threshold_value,
            anomaly_method=record.anomaly_method,
            window_seconds=record.window_seconds,
            min_samples=record.min_samples,
            consecutive_breaches_required=record.consecutive_breaches_required,
            severity=record.severity,
            enabled=record.enabled,
            consecutive_breaches=record.consecutive_breaches,
            last_evaluated_at=(
                record.last_evaluated_at.isoformat() if record.last_evaluated_at else None
            ),
            last_breached_at=(
                record.last_breached_at.isoformat() if record.last_breached_at else None
            ),
            created_at=record.created_at.isoformat(),
        )


SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def _validate_choices(
    signal_source: str | None,
    mode: str | None,
    comparison: str | None,
    anomaly_method: str | None,
    severity: str | None,
) -> None:
    """Reject unknown enum values up front with a message naming the options."""
    checks = (
        ("signal_source", signal_source, SIGNAL_SOURCES),
        ("mode", mode, MONITOR_MODES),
        ("comparison", comparison, COMPARISONS),
        ("anomaly_method", anomaly_method, ANOMALY_METHODS),
        ("severity", severity, SEVERITIES),
    )
    for field_name, value, allowed in checks:
        if value is not None and value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid {field_name} '{value}'. Allowed: {', '.join(allowed)}.",
            )


async def _require_application(repo: ApplicationRepository, app_id: str) -> None:
    if await repo.get_application(app_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found.",
        )


async def _require_monitor(
    repo: ApplicationRepository,
    app_id: str,
    monitor_id: str,
) -> MetricMonitorRecord:
    monitor = await repo.get_monitor(monitor_id)
    if monitor is None or monitor.app_id != app_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found for application '{app_id}'.",
        )
    return monitor


@router.post(
    "/{app_id}/monitors",
    response_model=MonitorResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
async def create_monitor(app_id: str, payload: MonitorCreate, repo: RepoDep) -> MonitorResponse:
    """Configure a new monitor on an application."""
    settings = get_settings()
    await _require_application(repo, app_id)
    _validate_choices(
        payload.signal_source,
        payload.mode,
        payload.comparison,
        payload.anomaly_method,
        payload.severity,
    )

    record = MetricMonitorRecord(
        monitor_id=f"mon-{uuid.uuid4().hex[:12]}",
        app_id=app_id,
        name=payload.name,
        signal_source=payload.signal_source,
        mode=payload.mode,
        comparison=payload.comparison,
        threshold_value=payload.threshold_value,
        anomaly_method=payload.anomaly_method,
        window_seconds=payload.window_seconds or settings.monitor_default_window_seconds,
        min_samples=payload.min_samples or settings.monitor_default_min_samples,
        consecutive_breaches_required=payload.consecutive_breaches_required,
        severity=payload.severity,
        enabled=payload.enabled,
    )
    await repo.save_monitor(record)
    return MonitorResponse.from_record(record)


@router.get("/{app_id}/monitors", response_model=list[MonitorResponse])
async def list_monitors(
    app_id: str,
    repo: RepoDep,
    enabled_only: bool = Query(default=False),
) -> list[MonitorResponse]:
    """List the monitors configured on an application."""
    await _require_application(repo, app_id)
    records = await repo.list_monitors(app_id=app_id, enabled_only=enabled_only)
    return [MonitorResponse.from_record(record) for record in records]


@router.get("/{app_id}/monitors/{monitor_id}", response_model=MonitorResponse)
async def get_monitor(app_id: str, monitor_id: str, repo: RepoDep) -> MonitorResponse:
    """Retrieve one monitor."""
    return MonitorResponse.from_record(await _require_monitor(repo, app_id, monitor_id))


@router.patch(
    "/{app_id}/monitors/{monitor_id}",
    response_model=MonitorResponse,
    dependencies=[Depends(require_api_key)],
)
async def update_monitor(
    app_id: str,
    monitor_id: str,
    payload: MonitorUpdate,
    repo: RepoDep,
) -> MonitorResponse:
    """Change a monitor's configuration."""
    await _require_monitor(repo, app_id, monitor_id)
    _validate_choices(
        payload.signal_source,
        payload.mode,
        payload.comparison,
        payload.anomaly_method,
        payload.severity,
    )
    updates = payload.model_dump(exclude_none=True)
    updated = await repo.update_monitor(monitor_id, updates)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found.",
        )
    return MonitorResponse.from_record(updated)


@router.delete(
    "/{app_id}/monitors/{monitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_key)],
)
async def delete_monitor(app_id: str, monitor_id: str, repo: RepoDep) -> Response:
    """Remove a monitor."""
    await _require_monitor(repo, app_id, monitor_id)
    await repo.delete_monitor(monitor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{app_id}/monitors/{monitor_id}/evaluate",
    response_model=dict[str, object],
    dependencies=[Depends(require_api_key)],
)
async def evaluate_monitor_now(app_id: str, monitor_id: str, repo: RepoDep) -> dict[str, object]:
    """Evaluate one monitor immediately against its recent samples."""
    from datetime import UTC, datetime, timedelta

    from src.core.monitor_evaluator import evaluate_monitor as run_evaluation

    settings = get_settings()
    monitor = await _require_monitor(repo, app_id, monitor_id)
    snapshots = await repo.list_probe_snapshots(
        app_id,
        since=datetime.now(UTC) - timedelta(seconds=monitor.window_seconds),
        limit=5000,
    )
    breach = run_evaluation(monitor, snapshots, settings=settings)
    if breach is None:
        return {
            "monitor_id": monitor_id,
            "breached": False,
            "samples": len(snapshots),
            "message": "Condition not met.",
        }
    return {
        "monitor_id": monitor_id,
        "breached": True,
        "samples": breach.sample_count,
        "observed_value": breach.observed_value,
        "threshold_value": breach.threshold_value,
        "severity": breach.severity,
        "message": breach.summary,
    }


# A separate router: under the applications prefix, "/monitors/options" would
# collide with "/{app_id}/monitors" and be read as app_id="monitors".
options_router = APIRouter(prefix="/api/v1/monitors", tags=["monitors"])


@options_router.get("/options", response_model=dict[str, list[str]])
async def monitor_options() -> dict[str, list[str]]:
    """Describe the valid monitor choices so the UI need not hardcode them."""
    return {
        "signal_sources": list(SIGNAL_SOURCES),
        "modes": list(MONITOR_MODES),
        "comparisons": list(COMPARISONS),
        "anomaly_methods": list(ANOMALY_METHODS),
        "severities": list(SEVERITIES),
    }
