"""DynamoDB incident repository for AWS Mode."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from config.settings import Settings, get_settings
from src.infrastructure.interfaces import ApplicationRecord, IncidentRecord
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

