"""Unified telemetry envelope and incident correlation across probe, git, and logs."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from src.core.drain_filter import DrainFilter

SignalSource = Literal["synthetic", "log", "metric", "git", "cloudwatch", "alertmanager"]


@dataclass
class TelemetrySignal:
    """Normalized ingestion envelope for every telemetry source."""

    signal_id: str
    source: SignalSource
    app_id: str
    service: str
    environment: str
    timestamp: datetime
    level: str = "INFO"
    metric_name: str | None = None
    metric_value: float | None = None
    raw_message: str | None = None
    pattern_template: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnifiedIncidentView:
    """One incident assembled from probe downtime, a git SHA, and a log cluster."""

    app_id: str
    title: str
    probable_cause: str
    evidence: list[str]
    deployment_sha: str | None = None
    log_template: str | None = None
    probe_summary: str | None = None


def correlate_signals(
    signals: list[TelemetrySignal],
    *,
    app_id: str,
    incident_time: datetime | None = None,
    window: timedelta = timedelta(minutes=15),
) -> UnifiedIncidentView:
    """Fold mixed signals for one application into a single incident view."""
    moment = incident_time or datetime.now(UTC)
    window_start = moment - window
    related = [
        signal
        for signal in signals
        if signal.app_id == app_id and _as_utc(signal.timestamp) >= window_start
    ]

    probe = _latest(related, "synthetic")
    git = _closest_git(related, moment)
    logs = [signal for signal in related if signal.source == "log" and signal.raw_message]
    template = _drain_template(logs)

    evidence: list[str] = []
    probe_summary = None
    if probe is not None:
        status = probe.metadata.get("http_status", 0)
        latency = probe.metadata.get("latency_ms", probe.metric_value or 0)
        probe_summary = f"Synthetic probe downtime: HTTP {status}, latency {latency}ms"
        evidence.append(probe_summary)

    deployment_sha = None
    if git is not None:
        deployment_sha = str(git.metadata.get("commit_sha") or "")
        short = deployment_sha[:7] if deployment_sha else "unknown"
        evidence.append(f"Closest git deployment {short}: {git.raw_message or git.service}")

    if template:
        evidence.append(f"Drain3 log cluster: {template}")

    title = f"{app_id} needs attention"
    cause = "Correlated telemetry did not identify a single cause."
    if probe is not None and deployment_sha:
        title = f"{app_id} is unavailable after a recent deployment"
        cause = f"Health checks failed after deployment {deployment_sha[:7]}" + (
            f" while logs matched '{template}'." if template else "."
        )
    elif probe is not None:
        title = f"{app_id} is unavailable"
        cause = probe_summary or "Synthetic health checks are failing."
    elif template:
        title = f"{app_id} is logging a repeating error"
        cause = f"Drain3 clustered the error pattern '{template}'."

    return UnifiedIncidentView(
        app_id=app_id,
        title=title,
        probable_cause=cause,
        evidence=evidence,
        deployment_sha=deployment_sha or None,
        log_template=template,
        probe_summary=probe_summary,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _latest(signals: list[TelemetrySignal], source: str) -> TelemetrySignal | None:
    matches = [signal for signal in signals if signal.source == source]
    if not matches:
        return None
    return max(matches, key=lambda signal: _as_utc(signal.timestamp))


def _closest_git(signals: list[TelemetrySignal], moment: datetime) -> TelemetrySignal | None:
    matches = [signal for signal in signals if signal.source == "git"]
    if not matches:
        return None
    moment = _as_utc(moment)

    def _distance(signal: TelemetrySignal) -> float:
        return abs((_as_utc(signal.timestamp) - moment).total_seconds())

    return min(matches, key=_distance)


def _drain_template(logs: list[TelemetrySignal]) -> str | None:
    lines = [signal.raw_message for signal in logs if signal.raw_message]
    if not lines:
        return None
    clusters = DrainFilter().cluster(lines)
    if not clusters:
        return logs[-1].pattern_template or lines[-1]
    top = max(clusters, key=lambda cluster: cluster.count)
    return top.template


class SQLiteTelemetryStore:
    """Persists recent telemetry signals beside the local SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_signals (
                    signal_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    app_id TEXT NOT NULL,
                    service TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    level TEXT,
                    metric_name TEXT,
                    metric_value REAL,
                    raw_message TEXT,
                    pattern_template TEXT,
                    metadata_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_telemetry_app_ts
                ON telemetry_signals(app_id, timestamp)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def save_signal(self, signal: TelemetrySignal) -> str:
        import json

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO telemetry_signals (
                    signal_id, source, app_id, service, environment, timestamp, level,
                    metric_name, metric_value, raw_message, pattern_template, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.signal_id or uuid.uuid4().hex,
                    signal.source,
                    signal.app_id,
                    signal.service,
                    signal.environment,
                    signal.timestamp.isoformat(),
                    signal.level,
                    signal.metric_name,
                    signal.metric_value,
                    signal.raw_message,
                    signal.pattern_template,
                    json.dumps(signal.metadata),
                ),
            )
            conn.commit()
        return signal.signal_id

    async def list_signals(
        self,
        app_id: str,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[TelemetrySignal]:
        import json

        query = "SELECT * FROM telemetry_signals WHERE app_id = ?"
        params: list[object] = [app_id]
        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        signals: list[TelemetrySignal] = []
        for row in rows:
            signals.append(
                TelemetrySignal(
                    signal_id=row["signal_id"],
                    source=row["source"],
                    app_id=row["app_id"],
                    service=row["service"],
                    environment=row["environment"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    level=row["level"] or "INFO",
                    metric_name=row["metric_name"],
                    metric_value=row["metric_value"],
                    raw_message=row["raw_message"],
                    pattern_template=row["pattern_template"],
                    metadata=json.loads(row["metadata_json"] or "{}"),
                )
            )
        return signals
