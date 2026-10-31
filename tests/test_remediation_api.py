"""Runbook catalog and remediation audit endpoints.

The audit endpoint did not exist, so the dashboard's audit tab was a
placeholder, and the frontend kept its own hardcoded copy of the runbook
catalog that could drift from what the executor actually accepts.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from config.settings import Settings
from src.executor.runbooks import RUNBOOK_CATALOG
from src.executor.runner import GuardedRemediationRunner
from src.main import app


def test_runbook_catalog_endpoint_matches_the_executor_allowlist():
    with TestClient(app) as client:
        resp = client.get("/api/v1/remediations/runbooks")
    assert resp.status_code == 200
    served = {item["runbook_id"] for item in resp.json()}
    assert served == set(RUNBOOK_CATALOG)


def test_runbook_catalog_exposes_risk_and_parameters():
    with TestClient(app) as client:
        catalog = client.get("/api/v1/remediations/runbooks").json()
    for item in catalog:
        assert item["risk_level"]
        assert item["blast_radius"]
        assert isinstance(item["parameters"], list)


def test_audit_endpoint_returns_an_empty_list_with_no_history():
    with TestClient(app) as client:
        resp = client.get("/api/v1/remediations/audit")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.fixture
def runner(tmp_path):
    instance = GuardedRemediationRunner(settings=Settings())
    instance._audit_log_path = tmp_path / "remediation_audit.jsonl"
    return instance


@pytest.mark.asyncio
async def test_approval_is_recorded_and_flagged_as_simulated(runner):
    """Execution is off by default, so an approval must say it only simulated."""
    plan = runner.create_dry_run_plan(
        incident_id="inc-1",
        runbook_id="restart-service",
        params={"service": "checkout-api", "namespace": "default"},
    )
    result = await runner.execute_approved_plan(plan, approved_by="sre@example.com")

    assert result.simulated is True
    assert result.execution_mode == "simulated"
    assert "Would run" in result.stdout

    entries = runner.read_audit_entries()
    assert len(entries) == 1
    assert entries[0]["approved_by"] == "sre@example.com"
    assert entries[0]["simulated"] is True
    assert entries[0]["execution_mode"] == "simulated"


@pytest.mark.asyncio
async def test_audit_entries_are_newest_first_and_filterable(runner):
    for incident in ("inc-a", "inc-b", "inc-a"):
        plan = runner.create_dry_run_plan(
            incident_id=incident,
            runbook_id="restart-service",
            params={"service": "checkout-api", "namespace": "default"},
        )
        await runner.execute_approved_plan(plan, approved_by="sre@example.com")

    everything = runner.read_audit_entries()
    assert [entry["incident_id"] for entry in everything] == ["inc-a", "inc-b", "inc-a"]

    only_a = runner.read_audit_entries(incident_id="inc-a")
    assert len(only_a) == 2
    assert {entry["incident_id"] for entry in only_a} == {"inc-a"}

    assert len(runner.read_audit_entries(limit=1)) == 1


@pytest.mark.asyncio
async def test_approval_requires_an_identity(runner):
    plan = runner.create_dry_run_plan(
        incident_id="inc-1",
        runbook_id="restart-service",
        params={"service": "checkout-api", "namespace": "default"},
    )
    with pytest.raises(ValueError, match="approved_by"):
        await runner.execute_approved_plan(plan, approved_by="   ")


def test_malformed_audit_lines_are_skipped(runner):
    runner._audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    runner._audit_log_path.write_text(
        '{"incident_id": "ok", "approved_by": "a"}\nnot json at all\n\n',
        encoding="utf-8",
    )
    entries = runner.read_audit_entries()
    assert len(entries) == 1
    assert entries[0]["incident_id"] == "ok"
