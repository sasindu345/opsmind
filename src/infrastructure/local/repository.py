"""SQLite-backed incident repository for Local Mode (Zero-AWS)."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from config.settings import PROJECT_ROOT, Settings, get_settings
from src.infrastructure.interfaces import IncidentRecord
from src.llm.schemas import AnalysisResult, IncidentStatus

logger = logging.getLogger("opsmind.infrastructure.sqlite")


class SQLiteIncidentRepository:
    """Stores incident metadata and timeline in a local SQLite database."""

    def __init__(
        self, db_path: str | Path | None = None, settings: Settings | None = None
    ) -> None:
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
            conn.commit()

    async def save_incident(self, result: AnalysisResult) -> str:
        record = IncidentRecord.from_analysis_result(result)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO incidents (
                    incident_id, service, environment, severity, status, created_at, resolved_at,
                    title, probable_cause, confidence, model, degraded, evidence_json,
                    report_uri, artifact_uri, timeline_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            datetime.now(UTC).isoformat()
            if new_status == IncidentStatus.RESOLVED
            else None
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
        resolved_at = (
            datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None
        )
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
            report_uri=row["report_uri"],
            artifact_uri=row["artifact_uri"],
            timeline_json=timeline,
        )
