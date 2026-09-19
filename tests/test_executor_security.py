import pytest

from src.executor.runbooks import RUNBOOK_CATALOG, get_runbook, validate_runbook_params
from src.executor.runner import GuardedRemediationRunner


def test_runbook_catalog_contains_expected_definitions():
    assert "rollback-deployment" in RUNBOOK_CATALOG
    assert "restart-service" in RUNBOOK_CATALOG
    assert "scale-workload" in RUNBOOK_CATALOG
    assert "clear-cache" in RUNBOOK_CATALOG
    assert "cordon-node" in RUNBOOK_CATALOG


def test_reject_unauthorized_runbook():
    runner = GuardedRemediationRunner()
    with pytest.raises(ValueError, match="not in the approved catalog"):
        runner.create_dry_run_plan(
            incident_id="inc-sec-1",
            runbook_id="arbitrary-bash-script",
            params={"cmd": "rm -rf /"},
        )


def test_reject_shell_injection_in_parameters():
    runbook = get_runbook("restart-service")
    assert runbook is not None

    # Attempt shell chaining injection in service name
    with pytest.raises(ValueError, match="violates validation pattern"):
        validate_runbook_params(runbook, {"service": "checkout; rm -rf /", "namespace": "default"})

    # Attempt path traversal / argument injection
    with pytest.raises(ValueError, match="violates validation pattern"):
        validate_runbook_params(
            runbook, {"service": "checkout", "namespace": "default && echo hacked"}
        )


def test_reject_out_of_bounds_replicas():
    runbook = get_runbook("scale-workload")
    assert runbook is not None

    # Too high replicas (max 20)
    with pytest.raises(ValueError, match="violates validation pattern"):
        validate_runbook_params(runbook, {"service": "checkout", "replicas": "100"})

    # Negative replicas
    with pytest.raises(ValueError, match="violates validation pattern"):
        validate_runbook_params(runbook, {"service": "checkout", "replicas": "-5"})


@pytest.mark.asyncio
async def test_dry_run_and_approved_execution_with_audit_trail(tmp_path):
    runner = GuardedRemediationRunner()
    runner._audit_log_path = tmp_path / "test_remediation_audit.jsonl"

    # 1. Create Dry Run Plan
    plan = runner.create_dry_run_plan(
        incident_id="inc-sec-100",
        runbook_id="restart-service",
        params={"service": "payment-api", "namespace": "production"},
    )

    assert plan.runbook_id == "restart-service"
    assert plan.argv == [
        "kubectl",
        "rollout",
        "restart",
        "deployment/payment-api",
        "-n",
        "production",
    ]
    assert "kubectl rollout restart deployment/payment-api -n production" in plan.command_preview
    assert plan.risk_level == "low"

    # 2. Execution must require approver identity
    with pytest.raises(ValueError, match="approved_by"):
        await runner.execute_approved_plan(plan, approved_by="", mock_execution=True)

    # 3. Approved Execution
    result = await runner.execute_approved_plan(
        plan,
        approved_by="sre-lead@company.com",
        reason="Pods failing readiness probe",
        mock_execution=True,
    )

    assert result.status == "success"
    assert result.approved_by == "sre-lead@company.com"
    assert result.exit_code == 0
    assert "payment-api" in result.stdout

    # 4. Verify Immutable Audit Log Written
    assert runner._audit_log_path.exists()
    audit_content = runner._audit_log_path.read_text(encoding="utf-8")
    assert "inc-sec-100" in audit_content
    assert "sre-lead@company.com" in audit_content
    assert "restart-service" in audit_content
