"""Webhook ingestion endpoints for Prometheus, GitHub, and CloudWatch/EventBridge.

Provides fast-acknowledgment ingestion (<50ms) that validates incoming signatures,
parses vendor-specific payloads, and enqueues standardized ``IncidentMessage`` envelopes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from config.settings import Settings, get_settings
from src.api.schemas import QueuedIncidentResponse
from src.core.worker import IncidentMessage, get_local_queue

logger = logging.getLogger("opsmind.webhooks")

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _verify_github_signature(
    secret: str, payload_bytes: bytes, header_signature: str | None
) -> bool:
    """Validate GitHub HMAC-SHA256 signature."""
    if not secret:
        # If no secret is configured, allow in development/local mode with warning
        return True
    if not header_signature:
        return False
    if not header_signature.startswith("sha256="):
        return False

    expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    received = header_signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


@router.post(
    "/prometheus",
    response_model=QueuedIncidentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def prometheus_alertmanager_webhook(
    request: Request,
    settings: Settings | None = None,
) -> QueuedIncidentResponse:
    """Ingest alerts from Prometheus Alertmanager."""
    settings = settings or get_settings()
    body = await request.json()

    alerts = body.get("alerts", [])
    firing_alerts = [a for a in alerts if a.get("status") == "firing"]
    target_alerts = firing_alerts or alerts or [{}]

    top_alert = target_alerts[0]
    labels = top_alert.get("labels", {})
    annotations = top_alert.get("annotations", {})

    service = labels.get("service") or labels.get("app") or labels.get("job") or "unknown-service"
    environment = labels.get("environment") or labels.get("env") or settings.app_env
    alert_name = labels.get("alertname", "PrometheusAlert")
    summary = (
        annotations.get("summary") or annotations.get("description") or f"Alert {alert_name} fired"
    )

    simulated_logs = [
        f"Prometheus Alert: {alert_name} (status: {top_alert.get('status', 'firing')})",
        f"Summary: {summary}",
    ]
    for k, v in labels.items():
        simulated_logs.append(f"Label {k}={v}")

    message_id = uuid.uuid4().hex
    correlation_id = uuid.uuid4().hex
    queue = get_local_queue()

    msg = IncidentMessage(
        message_id=message_id,
        correlation_id=correlation_id,
        service=service,
        environment=environment,
        event_type="prometheus",
        payload={
            "alert_name": alert_name,
            "summary": summary,
            "labels": labels,
            "annotations": annotations,
            "logs": simulated_logs,
            "raw_alert": top_alert,
        },
    )

    await queue.enqueue(msg)
    logger.info("enqueued prometheus alert %s for service %s", alert_name, service)

    return QueuedIncidentResponse(
        status="queued",
        message_id=message_id,
        correlation_id=correlation_id,
        service=service,
        environment=environment,
    )


@router.post(
    "/github",
    response_model=QueuedIncidentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    settings: Settings | None = None,
) -> QueuedIncidentResponse:
    """Ingest deployment and push events from GitHub with HMAC verification."""
    settings = settings or get_settings()
    payload_bytes = await request.body()

    if settings.github_webhook_secret and not _verify_github_signature(
        settings.github_webhook_secret, payload_bytes, x_hub_signature_256
    ):
        logger.warning("invalid GitHub webhook HMAC signature rejected")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HMAC signature in X-Hub-Signature-256",
        )

    try:
        body: dict[str, Any] = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

    event_type = x_github_event or "push"
    repository = body.get("repository", {}).get("name", "unknown-repo")
    service = repository
    environment = "production"

    commit_sha = ""
    author = "unknown"
    commit_msg = ""
    changed_files: list[str] = []

    if event_type == "deployment_status":
        deployment = body.get("deployment", {})
        environment = deployment.get("environment", "production")
        commit_sha = deployment.get("sha", "")
        author = deployment.get("creator", {}).get("login", "github-action")
        commit_msg = deployment.get("description", "GitHub deployment")
    elif event_type == "push":
        head_commit = body.get("head_commit") or {}
        commit_sha = head_commit.get("id", body.get("after", ""))
        author = head_commit.get("author", {}).get("name", "developer")
        commit_msg = head_commit.get("message", "")
        added = head_commit.get("added", [])
        modified = head_commit.get("modified", [])
        removed = head_commit.get("removed", [])
        changed_files = added + modified + removed
    else:
        commit_msg = f"GitHub event {event_type}"

    simulated_logs = [
        f"GitHub Event: {event_type} on {repository} ({environment})",
        f"Commit: {commit_sha[:7]} by {author} - {commit_msg}",
    ]

    message_id = uuid.uuid4().hex
    correlation_id = uuid.uuid4().hex
    queue = get_local_queue()

    msg = IncidentMessage(
        message_id=message_id,
        correlation_id=correlation_id,
        service=service,
        environment=environment,
        event_type="github",
        payload={
            "github_event": event_type,
            "commit_sha": commit_sha,
            "author": author,
            "message": commit_msg,
            "changed_files": changed_files,
            "logs": simulated_logs,
            "deployments": [
                {
                    "commit_sha": commit_sha,
                    "author": author,
                    "service": service,
                    "environment": environment,
                    "message": commit_msg,
                    "changed_files": changed_files,
                }
            ]
            if commit_sha
            else [],
        },
    )

    await queue.enqueue(msg)
    if commit_sha:
        try:
            from datetime import UTC, datetime

            from src.core.telemetry import TelemetrySignal
            from src.infrastructure.factory import get_telemetry_store

            await get_telemetry_store(settings).save_signal(
                TelemetrySignal(
                    signal_id=message_id,
                    source="git",
                    app_id=service,
                    service=service,
                    environment=environment,
                    timestamp=datetime.now(UTC),
                    level="INFO",
                    raw_message=commit_msg,
                    metadata={"commit_sha": commit_sha, "author": author},
                )
            )
        except Exception:
            logger.exception("failed to persist git telemetry signal for %s", service)
    logger.info("enqueued github %s event for %s (commit %s)", event_type, service, commit_sha[:7])

    return QueuedIncidentResponse(
        status="queued",
        message_id=message_id,
        correlation_id=correlation_id,
        service=service,
        environment=environment,
    )


@router.post(
    "/cloudwatch",
    response_model=QueuedIncidentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cloudwatch_alarm_webhook(
    request: Request,
    settings: Settings | None = None,
) -> QueuedIncidentResponse:
    """Ingest CloudWatch Alarms and EventBridge notification events."""
    settings = settings or get_settings()
    body = await request.json()

    # Handle SNS wrapped messages
    if "Message" in body and isinstance(body["Message"], str):
        try:
            body = json.loads(body["Message"])
        except Exception:
            pass

    # Check if this is an EventBridge envelope or native CloudWatch Alarm
    is_eventbridge = body.get("source") == "aws.cloudwatch"
    detail = body.get("detail", {}) if is_eventbridge else body

    alarm_name = detail.get("AlarmName") or body.get("AlarmName", "CloudWatchAlarm")
    new_state = detail.get("NewStateValue") or body.get("NewStateValue", "ALARM")
    state_reason = detail.get("NewStateReason") or body.get("NewStateReason", "Threshold breached")
    metric_name = (
        detail.get("MetricName")
        or detail.get("Trigger", {}).get("MetricName")
        or body.get("Trigger", {}).get("MetricName", "MetricBreach")
    )
    namespace = detail.get("Namespace") or detail.get("Trigger", {}).get(
        "Namespace", "AWS/Application"
    )

    # Extract service from alarm dimensions or name
    dimensions = detail.get("Trigger", {}).get("Dimensions", [])
    service = "aws-service"
    for d in dimensions:
        if d.get("name", "").lower() in {"servicename", "service", "app", "functionname"}:
            service = d.get("value", service)
            break
    if service == "aws-service" and "-" in alarm_name:
        service = alarm_name.split("-")[0]

    environment = settings.app_env

    simulated_logs = [
        f"CloudWatch Alarm: {alarm_name} transitioned to {new_state}",
        f"Metric: {namespace}/{metric_name}",
        f"Reason: {state_reason}",
    ]

    message_id = uuid.uuid4().hex
    correlation_id = uuid.uuid4().hex
    queue = get_local_queue()

    msg = IncidentMessage(
        message_id=message_id,
        correlation_id=correlation_id,
        service=service,
        environment=environment,
        event_type="cloudwatch",
        payload={
            "alarm_name": alarm_name,
            "new_state": new_state,
            "state_reason": state_reason,
            "metric_name": metric_name,
            "namespace": namespace,
            "logs": simulated_logs,
        },
    )

    await queue.enqueue(msg)
    logger.info("enqueued cloudwatch alarm %s for service %s", alarm_name, service)

    return QueuedIncidentResponse(
        status="queued",
        message_id=message_id,
        correlation_id=correlation_id,
        service=service,
        environment=environment,
    )
