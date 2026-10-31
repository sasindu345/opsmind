"""Remediation catalog and audit trail endpoints.

The runbook catalog is served from the executor's own allowlist so the dashboard
renders exactly what the backend will accept, instead of keeping its own copy.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from config.settings import get_settings
from src.executor.runbooks import RUNBOOK_CATALOG
from src.executor.runner import get_remediation_runner

router = APIRouter(prefix="/api/v1/remediations", tags=["remediation"])


class RunbookView(BaseModel):
    """A runbook as the dashboard needs to display it."""

    runbook_id: str
    name: str
    description: str
    risk_level: str
    blast_radius: str
    command_template: str
    parameters: list[str]
    default_params: dict[str, Any]


@router.get("/runbooks", response_model=list[RunbookView])
async def list_runbooks() -> list[RunbookView]:
    """Return the allowlisted runbook catalog."""
    return [
        RunbookView(
            runbook_id=runbook.runbook_id,
            name=runbook.name,
            description=runbook.description,
            risk_level=runbook.risk_level.value,
            blast_radius=runbook.blast_radius,
            command_template=" ".join(runbook.command_argv_template),
            parameters=sorted(runbook.param_validators),
            default_params=runbook.default_params,
        )
        for runbook in RUNBOOK_CATALOG.values()
    ]


@router.get("/audit", response_model=list[dict[str, Any]])
async def list_remediation_audit(
    incident_id: str | None = Query(default=None, description="Filter by incident"),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Return remediation audit entries, newest first.

    Every approved action is recorded here with who approved it, the exact
    argv that was built, and whether it actually executed or was simulated.
    """
    runner = get_remediation_runner(get_settings())
    return runner.read_audit_entries(incident_id=incident_id, limit=limit)
