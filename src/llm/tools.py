"""Read-only inspection tools for the operations copilot.

Every tool here only reads. There is deliberately no tool that executes a
runbook: the copilot may name a ``runbook_id`` for the operator to review, and
the existing dry-run and human-approval gates stay the only route to execution.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from config.settings import Settings, get_settings
from src.core.drain_filter import DrainFilter
from src.core.metrics import percentile
from src.infrastructure.factory import (
    get_application_repository,
    get_incident_repository,
    get_telemetry_store,
)

logger = logging.getLogger("opsmind.copilot.tools")


@dataclass
class ToolSpec:
    """One callable tool plus the schema the model is shown."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[dict[str, Any]]]

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _no_params() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "required": []}


def _app_param(extra: dict[str, Any] | None = None, required: bool = True) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "app_id": {"type": "string", "description": "Application identifier."}
    }
    properties.update(extra or {})
    return {
        "type": "object",
        "properties": properties,
        "required": ["app_id"] if required else [],
    }


class CopilotTools:
    """Builds the tool catalog bound to the active repositories."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._app_repo = get_application_repository(self.settings)
        self._incident_repo = get_incident_repository(self.settings)
        self._telemetry = get_telemetry_store(self.settings)

    # --- handlers ---------------------------------------------------------

    async def list_applications(self) -> dict[str, Any]:
        records = await self._app_repo.list_applications(limit=100)
        return {
            "applications": [
                {
                    "app_id": record.app_id,
                    "name": record.name,
                    "environment": record.environment,
                    "health_status": record.health_status,
                    "latency_ms": record.current_latency_ms,
                    "uptime_24h_percent": record.uptime_24h_percent,
                }
                for record in records
            ]
        }

    async def get_application_health(self, app_id: str) -> dict[str, Any]:
        record = await self._app_repo.get_application(app_id)
        if record is None:
            return {"error": f"No application named '{app_id}'."}
        return {
            "app_id": record.app_id,
            "name": record.name,
            "environment": record.environment,
            "health_status": record.health_status,
            "health_url": record.health_url,
            "current_latency_ms": record.current_latency_ms,
            "uptime_24h_percent": record.uptime_24h_percent,
            "consecutive_failures": record.consecutive_failures,
            "last_probe_at": record.last_probe_at.isoformat() if record.last_probe_at else None,
        }

    async def get_metrics_rollup(self, app_id: str, hours: int = 1) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 168)))
        snapshots = await self._app_repo.list_probe_snapshots(app_id, since=since, limit=5000)
        if not snapshots:
            return {"app_id": app_id, "samples": 0, "message": "No probe samples in this window."}

        latencies = [s.latency_ms for s in snapshots]
        successes = sum(1 for s in snapshots if s.is_success)
        return {
            "app_id": app_id,
            "window_hours": hours,
            "samples": len(snapshots),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
            "p95_latency_ms": percentile(latencies, 0.95),
            "max_latency_ms": round(max(latencies), 2),
            "availability_percent": round(100.0 * successes / len(snapshots), 2),
            "failed_probes": len(snapshots) - successes,
        }

    async def list_incidents(self, app_id: str | None = None, limit: int = 10) -> dict[str, Any]:
        records = await self._incident_repo.list_incidents(
            service=app_id, limit=max(1, min(limit, 50))
        )
        return {
            "incidents": [
                {
                    "incident_id": record.incident_id,
                    "service": record.service,
                    "title": record.title,
                    "severity": record.severity,
                    "status": record.status,
                    "probable_cause": record.probable_cause,
                    "confidence": record.confidence,
                    "created_at": record.created_at.isoformat(),
                    "deployment_sha": record.deployment_sha,
                }
                for record in records
            ]
        }

    async def get_incident(self, incident_id: str) -> dict[str, Any]:
        record = await self._incident_repo.get_incident(incident_id)
        if record is None:
            return {"error": f"No incident '{incident_id}'."}
        return {
            "incident_id": record.incident_id,
            "service": record.service,
            "title": record.title,
            "severity": record.severity,
            "status": record.status,
            "probable_cause": record.probable_cause,
            "confidence": record.confidence,
            "evidence": record.evidence_summary,
            "timeline": record.timeline_json,
            "deployment_sha": record.deployment_sha,
            "deployment_author": record.deployment_author,
        }

    async def get_recent_commits(self, app_id: str, hours: int = 24) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 720)))
        signals = await self._telemetry.list_signals(app_id, since=since)
        commits = [
            {
                "commit_sha": signal.metadata.get("commit_sha"),
                "author": signal.metadata.get("author"),
                "message": signal.raw_message,
                "repository": signal.metadata.get("repository"),
                "timestamp": signal.timestamp.isoformat(),
            }
            for signal in signals
            if signal.source == "git"
        ]
        return {"app_id": app_id, "commits": commits[:25], "count": len(commits)}

    async def get_log_patterns(self, app_id: str, hours: int = 6) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 168)))
        signals = await self._telemetry.list_signals(app_id, since=since)
        lines = [
            signal.raw_message
            for signal in signals
            if signal.raw_message and signal.source in {"log", "synthetic"}
        ]
        if not lines:
            return {"app_id": app_id, "patterns": [], "message": "No log signals in this window."}
        clusters = DrainFilter().cluster(lines)
        return {
            "app_id": app_id,
            "lines_analysed": len(lines),
            "patterns": [cluster.to_prompt_dict() for cluster in clusters[:10]],
        }

    async def search_incident_memory(self, query: str, top_k: int = 3) -> dict[str, Any]:
        from src.memory.vector_store import get_memory_store

        store = get_memory_store(self.settings)
        matches = await store.search(query, top_k=max(1, min(top_k, 10)))
        return {
            "query": query,
            "matches": [
                {
                    "incident_id": doc.incident_id,
                    "service": doc.service,
                    "title": doc.title,
                    "probable_cause": doc.probable_cause,
                    "recommended_actions": doc.recommended_actions,
                    "similarity": round(score, 4),
                }
                for doc, score in matches
            ],
        }

    # --- catalog ----------------------------------------------------------

    def catalog(self) -> dict[str, ToolSpec]:
        """The tools the copilot may call. Read-only by construction."""
        specs = [
            ToolSpec(
                name="list_applications",
                description="List every monitored application with its current health.",
                parameters=_no_params(),
                handler=self.list_applications,
            ),
            ToolSpec(
                name="get_application_health",
                description="Current health, latency and uptime for one application.",
                parameters=_app_param(),
                handler=self.get_application_health,
            ),
            ToolSpec(
                name="get_metrics_rollup",
                description=(
                    "Aggregated latency and availability for one application over a "
                    "window in hours. Use this to judge whether something is slow."
                ),
                parameters=_app_param(
                    {"hours": {"type": "integer", "description": "Window in hours, 1 to 168."}}
                ),
                handler=self.get_metrics_rollup,
            ),
            ToolSpec(
                name="list_incidents",
                description="Recent incidents, optionally filtered to one application.",
                parameters={
                    "type": "object",
                    "properties": {
                        "app_id": {"type": "string", "description": "Optional application filter."},
                        "limit": {"type": "integer", "description": "Maximum incidents, 1 to 50."},
                    },
                    "required": [],
                },
                handler=self.list_incidents,
            ),
            ToolSpec(
                name="get_incident",
                description="Full detail for one incident, including evidence and timeline.",
                parameters={
                    "type": "object",
                    "properties": {"incident_id": {"type": "string"}},
                    "required": ["incident_id"],
                },
                handler=self.get_incident,
            ),
            ToolSpec(
                name="get_recent_commits",
                description=(
                    "Commits recorded for an application. Use this to answer what changed."
                ),
                parameters=_app_param(
                    {"hours": {"type": "integer", "description": "Window in hours."}}
                ),
                handler=self.get_recent_commits,
            ),
            ToolSpec(
                name="get_log_patterns",
                description="Clustered log patterns for an application, most frequent first.",
                parameters=_app_param(
                    {"hours": {"type": "integer", "description": "Window in hours."}}
                ),
                handler=self.get_log_patterns,
            ),
            ToolSpec(
                name="search_incident_memory",
                description="Search resolved historical incidents for a similar past failure.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Free-text description."},
                        "top_k": {"type": "integer", "description": "Maximum matches, 1 to 10."},
                    },
                    "required": ["query"],
                },
                handler=self.search_incident_memory,
            ),
        ]
        return {spec.name: spec for spec in specs}
