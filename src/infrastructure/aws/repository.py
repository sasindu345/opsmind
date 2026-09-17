"""DynamoDB incident repository for AWS Mode."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from config.settings import Settings, get_settings
from src.core.telemetry import TelemetrySignal
from src.infrastructure.interfaces import ApplicationRecord, HealthProbeSnapshot, IncidentRecord
from src.llm.schemas import AnalysisResult, IncidentStatus

logger = logging.getLogger("opsmind.infrastructure.dynamodb")


class DynamoDBIncidentRepository:
    """Stores incident metadata in Amazon DynamoDB."""

    def __init__(
        self,
        table_name: str | None = None,
        region: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.table_name = table_name or self.settings.dynamodb_table_name
        self.region = region or self.settings.aws_region
        self._dynamodb = None
        self._table = None

    def _get_table(self):
        if self._table is None:
            import boto3

            self._dynamodb = boto3.resource("dynamodb", region_name=self.region)
            self._table = self._dynamodb.Table(self.table_name)
        return self._table

    async def save_incident(self, result: AnalysisResult) -> str:
        record = IncidentRecord.from_analysis_result(result)
        table = self._get_table()

        item: dict[str, Any] = {
            "incident_id": record.incident_id,
            "service": record.service,
            "environment": record.environment,
            "severity": record.severity,
            "status": record.status,
            "created_at": record.created_at.isoformat(),
            "title": record.title,
            "probable_cause": record.probable_cause,
            "confidence": Decimal(str(round(record.confidence, 4))),
            "model": record.model,
            "degraded": record.degraded,
            "evidence_summary": record.evidence_summary,
            "timeline_json": json.dumps(record.timeline_json),
        }
        if record.resolved_at:
            item["resolved_at"] = record.resolved_at.isoformat()
        if record.report_uri:
            item["report_uri"] = record.report_uri
        if record.artifact_uri:
            item["artifact_uri"] = record.artifact_uri
        if record.app_id:
            item["app_id"] = record.app_id
        if record.deployment_sha:
            item["deployment_sha"] = record.deployment_sha

        await asyncio.to_thread(table.put_item, Item=item)
        logger.info(
            "saved incident %s to DynamoDB table %s",
            record.incident_id[:8],
            self.table_name,
        )
        return record.incident_id

    async def get_incident(self, incident_id: str) -> IncidentRecord | None:
        table = self._get_table()
        resp = await asyncio.to_thread(table.get_item, Key={"incident_id": incident_id})
        item = resp.get("Item")
        if not item:
            return None
        return self._item_to_record(item)

    async def list_incidents(
        self,
        service: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[IncidentRecord]:
        table = self._get_table()
        kwargs: dict[str, Any] = {"Limit": limit}
        if service:
            from boto3.dynamodb.conditions import Attr

            kwargs["FilterExpression"] = Attr("service").eq(service)

        resp = await asyncio.to_thread(table.scan, **kwargs)
        items = resp.get("Items", [])
        return [self._item_to_record(item) for item in items]

    async def update_status(self, incident_id: str, new_status: IncidentStatus) -> bool:
        table = self._get_table()
        resolved_at = (
            datetime.now(UTC).isoformat() if new_status == IncidentStatus.RESOLVED else None
        )

        update_expr = "SET #s = :status"
        expr_attr_names = {"#s": "status"}
        expr_attr_values: dict[str, Any] = {":status": new_status.value}

        if resolved_at:
            update_expr += ", resolved_at = :res"
            expr_attr_values[":res"] = resolved_at

        try:
            await asyncio.to_thread(
                table.update_item,
                Key={"incident_id": incident_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_attr_names,
                ExpressionAttributeValues=expr_attr_values,
            )
            return True
        except Exception as exc:
            logger.error("failed updating DynamoDB status for %s: %s", incident_id, exc)
            return False

    def _item_to_record(self, item: dict[str, Any]) -> IncidentRecord:
        timeline = []
        if "timeline_json" in item and item["timeline_json"]:
            try:
                timeline = json.loads(item["timeline_json"])
            except Exception:
                pass

        resolved_at = (
            datetime.fromisoformat(item["resolved_at"]) if item.get("resolved_at") else None
        )

        return IncidentRecord(
            incident_id=str(item["incident_id"]),
            service=str(item.get("service", "unknown")),
            environment=str(item.get("environment", "production")),
            severity=str(item.get("severity", "medium")),
            status=str(item.get("status", "open")),
            created_at=datetime.fromisoformat(item["created_at"]),
            resolved_at=resolved_at,
            title=str(item.get("title", "")),
            probable_cause=str(item.get("probable_cause", "")),
            confidence=float(item.get("confidence", 0.0)),
            model=str(item.get("model", "")),
            degraded=bool(item.get("degraded", False)),
            evidence_summary=list(item.get("evidence_summary", [])),
            app_id=item.get("app_id"),
            deployment_sha=item.get("deployment_sha"),
            report_uri=item.get("report_uri"),
            artifact_uri=item.get("artifact_uri"),
            timeline_json=timeline,
        )


class DynamoDBApplicationRepository:
    """Stores application records in Amazon DynamoDB."""

    def __init__(
        self,
        table_name: str | None = None,
        region: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        suffix = "-incidents"
        base_name = self.settings.dynamodb_table_name.removesuffix(suffix)
        self.table_name = table_name or f"{base_name}-applications"
        self.region = region or self.settings.aws_region
        self._dynamodb = None
        self._table = None
        self._probes_table = None

    def _get_table(self):
        if self._table is None:
            import boto3

            self._dynamodb = boto3.resource("dynamodb", region_name=self.region)
            self._table = self._dynamodb.Table(self.table_name)
        return self._table

    async def save_application(self, app: ApplicationRecord) -> str:
        table = self._get_table()
        item: dict[str, Any] = {
            "app_id": app.app_id,
            "name": app.name,
            "description": app.description,
            "environment": app.environment,
            "owner_team": app.owner_team,
            "health_url": app.health_url,
            "probe_interval_seconds": app.probe_interval_seconds,
            "health_status": app.health_status,
            "consecutive_failures": app.consecutive_failures,
            "current_latency_ms": Decimal(str(round(app.current_latency_ms, 2))),
            "uptime_24h_percent": Decimal(str(round(app.uptime_24h_percent, 2))),
            "created_at": app.created_at.isoformat(),
            "updated_at": app.updated_at.isoformat(),
        }
        if app.last_probe_at:
            item["last_probe_at"] = app.last_probe_at.isoformat()

        await asyncio.to_thread(table.put_item, Item=item)
        logger.info("saved application %s (%s) to DynamoDB", app.app_id, app.name)
        return app.app_id

    async def get_application(self, app_id: str) -> ApplicationRecord | None:
        table = self._get_table()
        response = await asyncio.to_thread(table.get_item, Key={"app_id": app_id})
        item = response.get("Item")
        if not item:
            return None
        return self._item_to_record(item)

    async def list_applications(
        self,
        environment: str | None = None,
        limit: int = 100,
    ) -> list[ApplicationRecord]:
        table = self._get_table()
        scan_kwargs: dict[str, Any] = {"Limit": limit}

        if environment:
            from boto3.dynamodb.conditions import Attr

            scan_kwargs["FilterExpression"] = Attr("environment").eq(environment)

        response = await asyncio.to_thread(table.scan, **scan_kwargs)
        items = response.get("Items", [])
        return [self._item_to_record(item) for item in items]

    async def update_application(
        self,
        app_id: str,
        updates: dict[str, Any],
    ) -> ApplicationRecord | None:
        current = await self.get_application(app_id)
        if not current:
            return None

        allowed = {
            "name", "description", "environment", "owner_team", "health_url",
            "probe_interval_seconds", "health_status", "consecutive_failures",
            "current_latency_ms", "uptime_24h_percent", "last_probe_at",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return current

        for k, v in filtered.items():
            setattr(current, k, v)
        current.updated_at = datetime.now(UTC)

        await self.save_application(current)
        return current

    async def delete_application(self, app_id: str) -> bool:
        table = self._get_table()
        await asyncio.to_thread(table.delete_item, Key={"app_id": app_id})
        return True

    def _probes_table_name(self) -> str:
        return f"{self.table_name}-probes"

    def _get_probes_table(self):
        if not hasattr(self, "_probes_table") or self._probes_table is None:
            import boto3

            self._probes_table = boto3.resource("dynamodb", region_name=self.region).Table(
                self._probes_table_name()
            )
        return self._probes_table

    async def save_probe_snapshot(self, snapshot: HealthProbeSnapshot) -> str:
        table = self._get_probes_table()
        item: dict[str, Any] = {
            "probe_id": snapshot.probe_id,
            "app_id": snapshot.app_id,
            "timestamp": snapshot.timestamp.isoformat(),
            "http_status": snapshot.http_status,
            "latency_ms": Decimal(str(round(snapshot.latency_ms, 2))),
            "is_success": snapshot.is_success,
        }
        if snapshot.error_message:
            item["error_message"] = snapshot.error_message
        if snapshot.resolved_ip:
            item["resolved_ip"] = snapshot.resolved_ip
        await asyncio.to_thread(table.put_item, Item=item)
        return snapshot.probe_id

    async def list_probe_snapshots(
        self,
        app_id: str,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[HealthProbeSnapshot]:
        from boto3.dynamodb.conditions import Attr, Key

        table = self._get_probes_table()
        query_kwargs: dict[str, Any] = {
            "IndexName": "app_id-timestamp-index",
            "KeyConditionExpression": Key("app_id").eq(app_id),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if since is not None:
            query_kwargs["KeyConditionExpression"] = Key("app_id").eq(app_id) & Key(
                "timestamp"
            ).gte(since.isoformat())
        try:
            response = await asyncio.to_thread(table.query, **query_kwargs)
        except Exception:
            logger.exception("probe snapshot query failed for %s; falling back to scan", app_id)
            scan_kwargs: dict[str, Any] = {
                "FilterExpression": Attr("app_id").eq(app_id),
                "Limit": limit,
            }
            response = await asyncio.to_thread(table.scan, **scan_kwargs)
        return [self._item_to_snapshot(item) for item in response.get("Items", [])]

    def _item_to_snapshot(self, item: dict[str, Any]) -> HealthProbeSnapshot:
        return HealthProbeSnapshot(
            probe_id=str(item["probe_id"]),
            app_id=str(item["app_id"]),
            timestamp=datetime.fromisoformat(str(item["timestamp"])),
            http_status=int(item.get("http_status", 0)),
            latency_ms=float(item.get("latency_ms", 0.0)),
            is_success=bool(item.get("is_success", False)),
            error_message=item.get("error_message"),
            resolved_ip=item.get("resolved_ip"),
        )

    def _item_to_record(self, item: dict[str, Any]) -> ApplicationRecord:
        last_probe_at = (
            datetime.fromisoformat(item["last_probe_at"]) if item.get("last_probe_at") else None
        )
        return ApplicationRecord(
            app_id=str(item["app_id"]),
            name=str(item.get("name", "")),
            description=str(item.get("description", "")),
            environment=str(item.get("environment", "production")),
            owner_team=str(item.get("owner_team", "devops")),
            health_url=str(item.get("health_url", "")),
            probe_interval_seconds=int(item.get("probe_interval_seconds", 30)),
            health_status=str(item.get("health_status", "healthy")),
            consecutive_failures=int(item.get("consecutive_failures", 0)),
            current_latency_ms=float(item.get("current_latency_ms", 0.0)),
            uptime_24h_percent=float(item.get("uptime_24h_percent", 100.0)),
            last_probe_at=last_probe_at,
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )


class DynamoDBTelemetryStore:
    """Stores unified telemetry signals in a companion DynamoDB table."""

    def __init__(self, settings: Settings | None = None, table_name: str | None = None) -> None:
        self.settings = settings or get_settings()
        base = self.settings.dynamodb_table_name.removesuffix("-incidents")
        self.table_name = table_name or f"{base}-signals"
        self.region = self.settings.aws_region
        self._table = None

    def _get_table(self):
        if self._table is None:
            import boto3

            self._table = boto3.resource("dynamodb", region_name=self.region).Table(self.table_name)
        return self._table

    async def save_signal(self, signal: TelemetrySignal) -> str:
        item: dict[str, Any] = {
            "signal_id": signal.signal_id,
            "source": signal.source,
            "app_id": signal.app_id,
            "service": signal.service,
            "environment": signal.environment,
            "timestamp": signal.timestamp.isoformat(),
            "level": signal.level,
            "metadata_json": json.dumps(signal.metadata),
        }
        if signal.metric_name:
            item["metric_name"] = signal.metric_name
        if signal.metric_value is not None:
            item["metric_value"] = Decimal(str(signal.metric_value))
        if signal.raw_message:
            item["raw_message"] = signal.raw_message
        if signal.pattern_template:
            item["pattern_template"] = signal.pattern_template
        await asyncio.to_thread(self._get_table().put_item, Item=item)
        return signal.signal_id

    async def list_signals(
        self,
        app_id: str,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[TelemetrySignal]:
        from boto3.dynamodb.conditions import Attr

        response = await asyncio.to_thread(
            self._get_table().scan,
            FilterExpression=Attr("app_id").eq(app_id),
            Limit=limit,
        )
        signals = [self._item_to_signal(item) for item in response.get("Items", [])]
        if since is not None:
            signals = [signal for signal in signals if signal.timestamp >= since]
        signals.sort(key=lambda signal: signal.timestamp, reverse=True)
        return signals[:limit]

    def _item_to_signal(self, item: dict[str, Any]) -> TelemetrySignal:
        return TelemetrySignal(
            signal_id=str(item["signal_id"]),
            source=item.get("source", "log"),
            app_id=str(item.get("app_id", "")),
            service=str(item.get("service", "")),
            environment=str(item.get("environment", "production")),
            timestamp=datetime.fromisoformat(str(item["timestamp"])),
            level=str(item.get("level", "INFO")),
            metric_name=item.get("metric_name"),
            metric_value=(
                float(item["metric_value"]) if item.get("metric_value") is not None else None
            ),
            raw_message=item.get("raw_message"),
            pattern_template=item.get("pattern_template"),
            metadata=json.loads(item.get("metadata_json") or "{}"),
        )

