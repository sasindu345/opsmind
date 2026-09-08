"""Predefined remediation runbook definitions and parameters catalog."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Any


class RunbookRiskLevel(str, enum.Enum):
    """Risk tier of remediation action."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class RunbookDefinition:
    """Immutable specification for an executable runbook."""

    runbook_id: str
    name: str
    description: str
    risk_level: RunbookRiskLevel
    blast_radius: str
    binary: str
    command_argv_template: list[str]
    param_validators: dict[str, str] = field(default_factory=dict)
    default_params: dict[str, Any] = field(default_factory=dict)


# Safe Regex Validators
SERVICE_REGEX = r"^[a-zA-Z0-9_-]{1,63}$"
NAMESPACE_REGEX = r"^[a-zA-Z0-9_-]{1,63}$"
NODE_NAME_REGEX = r"^[a-zA-Z0-9_.-]{1,128}$"
HOST_REGEX = r"^[a-zA-Z0-9_.-]{1,253}$"
PORT_REGEX = (
    r"^(?:[1-9][0-9]{0,3}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5])$"
)
REPLICAS_REGEX = r"^[1-9]$|^1[0-9]$|^20$"  # 1 to 20 replicas max


RUNBOOK_CATALOG: dict[str, RunbookDefinition] = {
    "rollback-deployment": RunbookDefinition(
        runbook_id="rollback-deployment",
        name="Rollback Deployment",
        description="Rolls back a Kubernetes deployment to its previous stable revision.",
        risk_level=RunbookRiskLevel.MEDIUM,
        blast_radius="Service deployment pods only",
        binary="kubectl",
        command_argv_template=[
            "kubectl",
            "rollout",
            "undo",
            "deployment/{service}",
            "-n",
            "{namespace}",
        ],
        param_validators={
            "service": SERVICE_REGEX,
            "namespace": NAMESPACE_REGEX,
        },
        default_params={"namespace": "default"},
    ),
    "restart-service": RunbookDefinition(
        runbook_id="restart-service",
        name="Graceful Service Restart",
        description="Initiates a rolling restart of all pods in the target deployment.",
        risk_level=RunbookRiskLevel.LOW,
        blast_radius="Single service replicas",
        binary="kubectl",
        command_argv_template=[
            "kubectl",
            "rollout",
            "restart",
            "deployment/{service}",
            "-n",
            "{namespace}",
        ],
        param_validators={
            "service": SERVICE_REGEX,
            "namespace": NAMESPACE_REGEX,
        },
        default_params={"namespace": "default"},
    ),
    "scale-workload": RunbookDefinition(
        runbook_id="scale-workload",
        name="Scale Workload Replicas",
        description=(
            "Scales deployment replicas to alleviate CPU/memory saturation "
            "or handle traffic surges."
        ),
        risk_level=RunbookRiskLevel.MEDIUM,
        blast_radius="Service replica count",
        binary="kubectl",
        command_argv_template=[
            "kubectl",
            "scale",
            "deployment/{service}",
            "--replicas={replicas}",
            "-n",
            "{namespace}",
        ],
        param_validators={
            "service": SERVICE_REGEX,
            "namespace": NAMESPACE_REGEX,
            "replicas": REPLICAS_REGEX,
        },
        default_params={"namespace": "default", "replicas": "3"},
    ),
    "clear-cache": RunbookDefinition(
        runbook_id="clear-cache",
        name="Asynchronous Redis Cache Flush",
        description=(
            "Flushes transient cache keys asynchronously to clear stale states or bad keys."
        ),
        risk_level=RunbookRiskLevel.HIGH,
        blast_radius="Cache keyspace for target host",
        binary="redis-cli",
        command_argv_template=["redis-cli", "-h", "{host}", "-p", "{port}", "FLUSHDB", "ASYNC"],
        param_validators={
            "host": HOST_REGEX,
            "port": PORT_REGEX,
        },
        default_params={"host": "127.0.0.1", "port": "6379"},
    ),
    "cordon-node": RunbookDefinition(
        runbook_id="cordon-node",
        name="Cordon Unhealthy Node",
        description=(
            "Marks a Kubernetes node as unschedulable to prevent new pods on a failing host."
        ),
        risk_level=RunbookRiskLevel.HIGH,
        blast_radius="Cluster node scheduling",
        binary="kubectl",
        command_argv_template=["kubectl", "cordon", "{node_name}"],
        param_validators={
            "node_name": NODE_NAME_REGEX,
        },
        default_params={},
    ),
}


def get_runbook(runbook_id: str) -> RunbookDefinition | None:
    """Lookup a runbook by ID from the catalog."""
    return RUNBOOK_CATALOG.get(runbook_id)


def validate_runbook_params(runbook: RunbookDefinition, params: dict[str, Any]) -> dict[str, str]:
    """Validate user parameters against runbook regex validators.

    Raises ValueError if any parameter fails regex or is missing.
    """
    merged_params: dict[str, str] = {k: str(v) for k, v in runbook.default_params.items()}
    for k, v in params.items():
        if v is not None:
            merged_params[k] = str(v).strip()

    for param_name, regex in runbook.param_validators.items():
        val = merged_params.get(param_name)
        if val is None:
            raise ValueError(
                f"Missing required parameter '{param_name}' for runbook '{runbook.runbook_id}'"
            )
        if not re.match(regex, val):
            raise ValueError(
                f"Parameter '{param_name}' with value '{val}' violates validation pattern {regex}"
            )

    return merged_params
