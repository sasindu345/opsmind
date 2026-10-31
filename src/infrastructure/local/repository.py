"""SQLite-backed incident repository for Local Mode (Zero-AWS)."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import PROJECT_ROOT, Settings, get_settings
from src.infrastructure.interfaces import (
    ApplicationRecord,
    HealthProbeSnapshot,
    IncidentRecord,
    MetricMonitorRecord,
    RepositoryRecord,
)
from src.llm.schemas import AnalysisResult, IncidentStatus

logger = logging.getLogger("opsmind.infrastructure.sqlite")


class SQLiteIncidentRepository:
    """Stores incident metadata and timeline in a local SQLite database."""

    def __init__(self, db_path: str | Path | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if db_path is None:
            raw_url = self.settings.database_url
            if raw_url.startswith("sqlite:///"):
                subpath = raw_url.removeprefix("sqlite:///")
                self.db_path = (PROJECT_ROOT / subpath).resolve()
            else:
                self.db_path = (PROJECT_ROOT / "opsmind.db").resolve()
        else:
            self.db_path = Path(db_path)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create incidents and timeline tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    service TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    title TEXT,
                    probable_cause TEXT,
                    confidence REAL,
                    model TEXT,
                    degraded INTEGER,
                    evidence_json TEXT,
                    report_uri TEXT,
                    artifact_uri TEXT,
                    timeline_json TEXT
                )
                """
            )
            self._ensure_column(conn, "incidents", "app_id", "TEXT")
            self._ensure_column(conn, "incidents", "deployment_sha", "TEXT")
            conn.commit()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, typedef: str) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")

    async def save_incident(self, result: AnalysisResult) -> str:
        record = IncidentRecord.from_analysis_result(result)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO incidents (
                    incident_id, service, environment, severity, status, created_at, resolved_at,
                    title, probable_cause, confidence, model, degraded, evidence_json,
                    report_uri, artifact_uri, timeline_json, app_id, deployment_sha
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.incident_id,
                    record.service,
                    record.environment,
                    record.severity,
                    record.status,
                    record.created_at.isoformat(),
                    record.resolved_at.isoformat() if record.resolved_at else None,
                    record.title,
                    record.probable_cause,
                    record.confidence,
                    record.model,
                    1 if record.degraded else 0,
                    json.dumps(record.evidence_summary),
                    record.report_uri,
                    record.artifact_uri,
                    json.dumps(record.timeline_json),
                    record.app_id,
                    record.deployment_sha,
                ),
            )
            conn.commit()
        logger.info("saved incident %s to SQLite repository", record.incident_id[:8])
        return record.incident_id

    async def get_incident(self, incident_id: str) -> IncidentRecord | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    async def list_incidents(
        self,
        service: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[IncidentRecord]:
        query = "SELECT * FROM incidents WHERE 1=1"
        params: list[object] = []
        if service:
            query += " AND service = ?"
            params.append(service)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_record(r) for r in rows]

    async def update_status(self, incident_id: str, new_status: IncidentStatus) -> bool:
        resolved_at = (
            datetime.now(UTC).isoformat() if new_status == IncidentStatus.RESOLVED else None
        )
        sql = (
            "UPDATE incidents SET status = ?, "
            "resolved_at = COALESCE(?, resolved_at) WHERE incident_id = ?"
        )
        with self._get_connection() as conn:
            cursor = conn.execute(
                sql,
                (new_status.value, resolved_at, incident_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_record(self, row: sqlite3.Row) -> IncidentRecord:
        created_at = datetime.fromisoformat(row["created_at"])
        resolved_at = datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None
        evidence = json.loads(row["evidence_json"]) if row["evidence_json"] else []
        timeline = json.loads(row["timeline_json"]) if row["timeline_json"] else []

        return IncidentRecord(
            incident_id=row["incident_id"],
            service=row["service"],
            environment=row["environment"],
            severity=row["severity"],
            status=row["status"],
            created_at=created_at,
            resolved_at=resolved_at,
            title=row["title"] or "",
            probable_cause=row["probable_cause"] or "",
            confidence=float(row["confidence"] or 0.0),
            model=row["model"] or "",
            degraded=bool(row["degraded"]),
            evidence_summary=evidence,
            app_id=row["app_id"] if "app_id" in row.keys() else None,
            deployment_sha=row["deployment_sha"] if "deployment_sha" in row.keys() else None,
            report_uri=row["report_uri"],
            artifact_uri=row["artifact_uri"],
            timeline_json=timeline,
        )


class SQLiteApplicationRepository:
    """Stores application records in local SQLite database."""

    def __init__(self, db_path: str | Path | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if db_path is None:
            raw_url = self.settings.database_url
            if raw_url.startswith("sqlite:///"):
                subpath = raw_url.removeprefix("sqlite:///")
                self.db_path = (PROJECT_ROOT / subpath).resolve()
            else:
                self.db_path = (PROJECT_ROOT / "opsmind.db").resolve()
        else:
            self.db_path = Path(db_path)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    app_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    environment TEXT NOT NULL,
                    owner_team TEXT NOT NULL,
                    health_url TEXT,
                    probe_interval_seconds INTEGER DEFAULT 30,
                    health_status TEXT NOT NULL,
                    consecutive_failures INTEGER DEFAULT 0,
                    current_latency_ms REAL DEFAULT 0.0,
                    uptime_24h_percent REAL DEFAULT 100.0,
                    last_probe_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS health_probe_snapshots (
                    probe_id TEXT PRIMARY KEY,
                    app_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    http_status INTEGER NOT NULL,
                    latency_ms REAL NOT NULL,
                    is_success INTEGER NOT NULL,
                    error_message TEXT,
                    resolved_ip TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_health_probes_app_ts
                ON health_probe_snapshots(app_id, timestamp)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metric_monitors (
                    monitor_id TEXT PRIMARY KEY,
                    app_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    signal_source TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    comparison TEXT NOT NULL,
                    threshold_value REAL NOT NULL,
                    anomaly_method TEXT NOT NULL,
                    window_seconds INTEGER NOT NULL,
                    min_samples INTEGER NOT NULL,
                    consecutive_breaches_required INTEGER NOT NULL,
                    severity TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    consecutive_breaches INTEGER DEFAULT 0,
                    last_evaluated_at TEXT,
                    last_breached_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_metric_monitors_app
                ON metric_monitors(app_id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS repositories (
                    repo_id TEXT PRIMARY KEY,
                    app_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    default_branch TEXT NOT NULL,
                    token_secret_ref TEXT,
                    poll_interval_seconds INTEGER NOT NULL,
                    commits_enabled INTEGER NOT NULL,
                    actions_enabled INTEGER NOT NULL,
                    last_commit_sha TEXT,
                    commits_etag TEXT,
                    last_workflow_run_id INTEGER,
                    runs_etag TEXT,
                    rate_limit_remaining INTEGER,
                    last_polled_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_repositories_app
                ON repositories(app_id)
                """
            )
            conn.commit()

    async def save_application(self, app: ApplicationRecord) -> str:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO applications (
                    app_id, name, description, environment, owner_team, health_url,
                    probe_interval_seconds, health_status, consecutive_failures,
                    current_latency_ms, uptime_24h_percent, last_probe_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    app.app_id,
                    app.name,
                    app.description,
                    app.environment,
                    app.owner_team,
                    app.health_url,
                    app.probe_interval_seconds,
                    app.health_status,
                    app.consecutive_failures,
                    app.current_latency_ms,
                    app.uptime_24h_percent,
                    app.last_probe_at.isoformat() if app.last_probe_at else None,
                    app.created_at.isoformat(),
                    app.updated_at.isoformat(),
                ),
            )
            conn.commit()
        logger.info("saved application %s (%s) to SQLite repository", app.app_id, app.name)
        return app.app_id

    async def get_application(self, app_id: str) -> ApplicationRecord | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM applications WHERE app_id = ?", (app_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    async def list_applications(
        self,
        environment: str | None = None,
        limit: int = 100,
    ) -> list[ApplicationRecord]:
        with self._get_connection() as conn:
            if environment:
                cursor = conn.execute(
                    "SELECT * FROM applications WHERE environment = ? ORDER BY name ASC LIMIT ?",
                    (environment, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM applications ORDER BY name ASC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]

    async def update_application(
        self,
        app_id: str,
        updates: dict[str, Any],
    ) -> ApplicationRecord | None:
        current = await self.get_application(app_id)
        if not current:
            return None

        allowed = {
            "name",
            "description",
            "environment",
            "owner_team",
            "health_url",
            "probe_interval_seconds",
            "health_status",
            "consecutive_failures",
            "current_latency_ms",
            "uptime_24h_percent",
            "last_probe_at",
        }
        filtered_updates = {k: v for k, v in updates.items() if k in allowed}
        if not filtered_updates:
            return current

        filtered_updates["updated_at"] = datetime.now(UTC).isoformat()
        probe_at = filtered_updates.get("last_probe_at")
        if isinstance(probe_at, datetime):
            filtered_updates["last_probe_at"] = probe_at.isoformat()

        set_clauses = [f"{col} = ?" for col in filtered_updates.keys()]
        values = list(filtered_updates.values()) + [app_id]

        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE applications SET {', '.join(set_clauses)} WHERE app_id = ?",
                values,
            )
            conn.commit()

        return await self.get_application(app_id)

    async def delete_application(self, app_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM applications WHERE app_id = ?", (app_id,))
            conn.execute("DELETE FROM health_probe_snapshots WHERE app_id = ?", (app_id,))
            conn.execute("DELETE FROM metric_monitors WHERE app_id = ?", (app_id,))
            conn.execute("DELETE FROM repositories WHERE app_id = ?", (app_id,))
            conn.commit()
            return cursor.rowcount > 0

    async def save_probe_snapshot(self, snapshot: HealthProbeSnapshot) -> str:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO health_probe_snapshots (
                    probe_id, app_id, timestamp, http_status, latency_ms,
                    is_success, error_message, resolved_ip
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.probe_id,
                    snapshot.app_id,
                    snapshot.timestamp.isoformat(),
                    snapshot.http_status,
                    snapshot.latency_ms,
                    1 if snapshot.is_success else 0,
                    snapshot.error_message,
                    snapshot.resolved_ip,
                ),
            )
            conn.commit()
        return snapshot.probe_id

    async def list_probe_snapshots(
        self,
        app_id: str,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[HealthProbeSnapshot]:
        query = "SELECT * FROM health_probe_snapshots WHERE app_id = ?"
        params: list[object] = [app_id]
        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._probe_row_to_snapshot(row) for row in rows]

    def _probe_row_to_snapshot(self, row: sqlite3.Row) -> HealthProbeSnapshot:
        return HealthProbeSnapshot(
            probe_id=row["probe_id"],
            app_id=row["app_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            http_status=int(row["http_status"]),
            latency_ms=float(row["latency_ms"]),
            is_success=bool(row["is_success"]),
            error_message=row["error_message"],
            resolved_ip=row["resolved_ip"],
        )

    async def save_monitor(self, monitor: MetricMonitorRecord) -> str:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO metric_monitors (
                    monitor_id, app_id, name, signal_source, mode, comparison,
                    threshold_value, anomaly_method, window_seconds, min_samples,
                    consecutive_breaches_required, severity, enabled,
                    consecutive_breaches, last_evaluated_at, last_breached_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    monitor.monitor_id,
                    monitor.app_id,
                    monitor.name,
                    monitor.signal_source,
                    monitor.mode,
                    monitor.comparison,
                    monitor.threshold_value,
                    monitor.anomaly_method,
                    monitor.window_seconds,
                    monitor.min_samples,
                    monitor.consecutive_breaches_required,
                    monitor.severity,
                    int(monitor.enabled),
                    monitor.consecutive_breaches,
                    monitor.last_evaluated_at.isoformat() if monitor.last_evaluated_at else None,
                    monitor.last_breached_at.isoformat() if monitor.last_breached_at else None,
                    monitor.created_at.isoformat(),
                    monitor.updated_at.isoformat(),
                ),
            )
            conn.commit()
        return monitor.monitor_id

    async def get_monitor(self, monitor_id: str) -> MetricMonitorRecord | None:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM metric_monitors WHERE monitor_id = ?",
                (monitor_id,),
            )
            row = cursor.fetchone()
            return self._row_to_monitor(row) if row else None

    async def list_monitors(
        self,
        app_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[MetricMonitorRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if app_id:
            clauses.append("app_id = ?")
            params.append(app_id)
        if enabled_only:
            clauses.append("enabled = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"SELECT * FROM metric_monitors {where} ORDER BY created_at ASC",
                params,
            )
            return [self._row_to_monitor(row) for row in cursor.fetchall()]

    async def update_monitor(
        self,
        monitor_id: str,
        updates: dict[str, Any],
    ) -> MetricMonitorRecord | None:
        current = await self.get_monitor(monitor_id)
        if not current:
            return None

        allowed = {
            "name",
            "signal_source",
            "mode",
            "comparison",
            "threshold_value",
            "anomaly_method",
            "window_seconds",
            "min_samples",
            "consecutive_breaches_required",
            "severity",
            "enabled",
            "consecutive_breaches",
            "last_evaluated_at",
            "last_breached_at",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return current

        if "enabled" in filtered:
            filtered["enabled"] = int(bool(filtered["enabled"]))
        for key in ("last_evaluated_at", "last_breached_at"):
            if isinstance(filtered.get(key), datetime):
                filtered[key] = filtered[key].isoformat()

        filtered["updated_at"] = datetime.now(UTC).isoformat()
        set_clauses = [f"{col} = ?" for col in filtered]
        values = list(filtered.values()) + [monitor_id]
        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE metric_monitors SET {', '.join(set_clauses)} WHERE monitor_id = ?",
                values,
            )
            conn.commit()
        return await self.get_monitor(monitor_id)

    async def delete_monitor(self, monitor_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM metric_monitors WHERE monitor_id = ?",
                (monitor_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    async def save_repository(self, repo: RepositoryRecord) -> str:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO repositories (
                    repo_id, app_id, owner, name, default_branch, token_secret_ref,
                    poll_interval_seconds, commits_enabled, actions_enabled,
                    last_commit_sha, commits_etag, last_workflow_run_id, runs_etag,
                    rate_limit_remaining, last_polled_at, last_error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repo.repo_id,
                    repo.app_id,
                    repo.owner,
                    repo.name,
                    repo.default_branch,
                    repo.token_secret_ref,
                    repo.poll_interval_seconds,
                    int(repo.commits_enabled),
                    int(repo.actions_enabled),
                    repo.last_commit_sha,
                    repo.commits_etag,
                    repo.last_workflow_run_id,
                    repo.runs_etag,
                    repo.rate_limit_remaining,
                    repo.last_polled_at.isoformat() if repo.last_polled_at else None,
                    repo.last_error,
                    repo.created_at.isoformat(),
                    repo.updated_at.isoformat(),
                ),
            )
            conn.commit()
        return repo.repo_id

    async def get_repository(self, repo_id: str) -> RepositoryRecord | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM repositories WHERE repo_id = ?", (repo_id,))
            row = cursor.fetchone()
            return self._row_to_repository(row) if row else None

    async def list_repositories(self, app_id: str | None = None) -> list[RepositoryRecord]:
        with self._get_connection() as conn:
            if app_id:
                cursor = conn.execute(
                    "SELECT * FROM repositories WHERE app_id = ? ORDER BY created_at ASC",
                    (app_id,),
                )
            else:
                cursor = conn.execute("SELECT * FROM repositories ORDER BY created_at ASC")
            return [self._row_to_repository(row) for row in cursor.fetchall()]

    async def update_repository(
        self,
        repo_id: str,
        updates: dict[str, Any],
    ) -> RepositoryRecord | None:
        current = await self.get_repository(repo_id)
        if not current:
            return None

        allowed = {
            "app_id",
            "default_branch",
            "token_secret_ref",
            "poll_interval_seconds",
            "commits_enabled",
            "actions_enabled",
            "last_commit_sha",
            "commits_etag",
            "last_workflow_run_id",
            "runs_etag",
            "rate_limit_remaining",
            "last_polled_at",
            "last_error",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return current

        for key in ("commits_enabled", "actions_enabled"):
            if key in filtered:
                filtered[key] = int(bool(filtered[key]))
        if isinstance(filtered.get("last_polled_at"), datetime):
            filtered["last_polled_at"] = filtered["last_polled_at"].isoformat()

        filtered["updated_at"] = datetime.now(UTC).isoformat()
        set_clauses = [f"{col} = ?" for col in filtered]
        values = list(filtered.values()) + [repo_id]
        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE repositories SET {', '.join(set_clauses)} WHERE repo_id = ?",
                values,
            )
            conn.commit()
        return await self.get_repository(repo_id)

    async def delete_repository(self, repo_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM repositories WHERE repo_id = ?", (repo_id,))
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_repository(self, row: sqlite3.Row) -> RepositoryRecord:
        polled = row["last_polled_at"]
        return RepositoryRecord(
            repo_id=row["repo_id"],
            app_id=row["app_id"],
            owner=row["owner"],
            name=row["name"],
            default_branch=row["default_branch"],
            token_secret_ref=row["token_secret_ref"] or "",
            poll_interval_seconds=int(row["poll_interval_seconds"]),
            commits_enabled=bool(row["commits_enabled"]),
            actions_enabled=bool(row["actions_enabled"]),
            last_commit_sha=row["last_commit_sha"],
            commits_etag=row["commits_etag"],
            last_workflow_run_id=(
                int(row["last_workflow_run_id"])
                if row["last_workflow_run_id"] is not None
                else None
            ),
            runs_etag=row["runs_etag"],
            rate_limit_remaining=(
                int(row["rate_limit_remaining"])
                if row["rate_limit_remaining"] is not None
                else None
            ),
            last_polled_at=datetime.fromisoformat(polled) if polled else None,
            last_error=row["last_error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_monitor(self, row: sqlite3.Row) -> MetricMonitorRecord:
        evaluated = row["last_evaluated_at"]
        breached = row["last_breached_at"]
        return MetricMonitorRecord(
            monitor_id=row["monitor_id"],
            app_id=row["app_id"],
            name=row["name"],
            signal_source=row["signal_source"],
            mode=row["mode"],
            comparison=row["comparison"],
            threshold_value=float(row["threshold_value"]),
            anomaly_method=row["anomaly_method"],
            window_seconds=int(row["window_seconds"]),
            min_samples=int(row["min_samples"]),
            consecutive_breaches_required=int(row["consecutive_breaches_required"]),
            severity=row["severity"],
            enabled=bool(row["enabled"]),
            consecutive_breaches=int(row["consecutive_breaches"] or 0),
            last_evaluated_at=datetime.fromisoformat(evaluated) if evaluated else None,
            last_breached_at=datetime.fromisoformat(breached) if breached else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_record(self, row: sqlite3.Row) -> ApplicationRecord:
        created_at = datetime.fromisoformat(row["created_at"])
        updated_at = datetime.fromisoformat(row["updated_at"])
        raw_probe = row["last_probe_at"]
        last_probe_at = datetime.fromisoformat(raw_probe) if raw_probe else None

        return ApplicationRecord(
            app_id=row["app_id"],
            name=row["name"],
            description=row["description"] or "",
            environment=row["environment"],
            owner_team=row["owner_team"],
            health_url=row["health_url"] or "",
            probe_interval_seconds=int(row["probe_interval_seconds"] or 30),
            health_status=row["health_status"],
            consecutive_failures=int(row["consecutive_failures"] or 0),
            current_latency_ms=float(row["current_latency_ms"] or 0.0),
            uptime_24h_percent=float(row["uptime_24h_percent"] or 100.0),
            last_probe_at=last_probe_at,
            created_at=created_at,
            updated_at=updated_at,
        )
