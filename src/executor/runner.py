"""Guarded remediation runner enforcing allowlists, dry-runs, and audit logs."""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from config.settings import PROJECT_ROOT, Settings, get_settings
from src.executor.runbooks import RunbookDefinition, get_runbook, validate_runbook_params

logger = logging.getLogger("opsmind.executor.runner")


@dataclass
class RemediationPlan:
    """Preview plan for a remediation action before execution."""

    plan_id: str
    incident_id: str
    runbook_id: str
    runbook_name: str
    risk_level: str
    blast_radius: str
    argv: list[str]
    command_preview: str
    parameters: dict[str, str]
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class RemediationExecutionResult:
    """Execution outcome with complete immutable audit trail details."""

    execution_id: str
    plan_id: str
    incident_id: str
    runbook_id: str
    approved_by: str
    reason: str
    status: str  # success, failed
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    executed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    audit_entry: dict[str, Any] = field(default_factory=dict)


class GuardedRemediationRunner:
    """Guarded runner that strictly checks allowlists, produces dry-runs, and records audits."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._audit_log_path = (PROJECT_ROOT / "data" / "remediation_audit.jsonl").resolve()
        self._pending_plans: dict[str, RemediationPlan] = {}

    def create_dry_run_plan(
        self,
        incident_id: str,
        runbook_id: str,
        params: dict[str, Any],
    ) -> RemediationPlan:
        """Construct and validate a dry-run remediation plan without executing anything."""
        runbook: RunbookDefinition | None = get_runbook(runbook_id)
        if not runbook:
            raise ValueError(
                f"Unknown runbook '{runbook_id}'. Action is not in the approved catalog."
            )

        # Strict parameter validation
        validated_params = validate_runbook_params(runbook, params)

        # Assemble argv with shell=False safety
        argv: list[str] = []
        for arg in runbook.command_argv_template:
            formatted = arg.format(**validated_params)
            argv.append(formatted)

        plan = RemediationPlan(
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            incident_id=incident_id,
            runbook_id=runbook.runbook_id,
            runbook_name=runbook.name,
            risk_level=runbook.risk_level.value,
            blast_radius=runbook.blast_radius,
            argv=argv,
            command_preview=" ".join(shlex.quote(a) for a in argv),
            parameters=validated_params,
        )

        self._pending_plans[plan.plan_id] = plan
        logger.info(
            "Created dry-run remediation plan %s for incident %s", plan.plan_id, incident_id
        )
        return plan

    def get_plan(self, plan_id: str) -> RemediationPlan | None:
        """Lookup an existing dry-run plan."""
        return self._pending_plans.get(plan_id)

    async def execute_approved_plan(
        self,
        plan: RemediationPlan,
        approved_by: str,
        reason: str = "Operator approved via ChatOps / API",
        mock_execution: bool = False,
    ) -> RemediationExecutionResult:
        """Execute a previously previewed remediation plan with shell=False."""
        if not approved_by or not approved_by.strip():
            raise ValueError("Remediation execution requires an explicit 'approved_by' identity.")

        start_time = time.perf_counter()
        execution_id = f"exec-{uuid.uuid4().hex[:12]}"

        # Always shell=False execution for security
        exit_code = 0
        stdout = ""
        stderr = ""
        status = "success"

        if mock_execution or self.settings.deployment_mode.value == "local":
            # Safe local simulation if binary isn't in test environment
            stdout = f"[OpsMind Simulated Execution] Ran: {plan.command_preview}"
            stderr = ""
            exit_code = 0
            status = "success"
        else:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *plan.argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=30.0
                )
                exit_code = proc.returncode or 0
                stdout = stdout_bytes.decode(errors="replace")
                stderr = stderr_bytes.decode(errors="replace")
                status = "success" if exit_code == 0 else "failed"
            except Exception as exc:
                exit_code = 1
                status = "failed"
                stderr = f"Execution failed: {exc}"
                logger.error("Error executing remediation plan %s: %s", plan.plan_id, exc)

        duration = time.perf_counter() - start_time

        audit_entry = {
            "execution_id": execution_id,
            "plan_id": plan.plan_id,
            "incident_id": plan.incident_id,
            "runbook_id": plan.runbook_id,
            "approved_by": approved_by,
            "reason": reason,
            "argv": plan.argv,
            "command_preview": plan.command_preview,
            "parameters": plan.parameters,
            "exit_code": exit_code,
            "status": status,
            "duration_seconds": round(duration, 4),
            "timestamp": datetime.now(UTC).isoformat(),
        }

        self._record_audit_log(audit_entry)

        return RemediationExecutionResult(
            execution_id=execution_id,
            plan_id=plan.plan_id,
            incident_id=plan.incident_id,
            runbook_id=plan.runbook_id,
            approved_by=approved_by,
            reason=reason,
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=round(duration, 4),
            audit_entry=audit_entry,
        )

    def _record_audit_log(self, entry: dict[str, Any]) -> None:
        """Append immutable audit log entry."""
        try:
            self._audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._audit_log_path, mode="a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.error("Failed to write remediation audit log: %s", exc)


_runner_instance: GuardedRemediationRunner | None = None


def get_remediation_runner(settings: Settings | None = None) -> GuardedRemediationRunner:
    """Retrieve or create the singleton GuardedRemediationRunner instance."""
    global _runner_instance
    if _runner_instance is None:
        _runner_instance = GuardedRemediationRunner(settings=settings)
    return _runner_instance
