"""AWS EventBridge event publisher."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from config.settings import Settings, get_settings

logger = logging.getLogger("opsmind.infrastructure.eventbridge")


class AWSEventPublisher:
    """Publishes incidents and alerts to Amazon EventBridge custom event bus."""

    def __init__(
        self,
        bus_name: str | None = None,
        region: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.bus_name = bus_name or self.settings.eventbridge_bus_name
        self.region = region or self.settings.aws_region
        self._events = None

    def _get_client(self):
        if self._events is None:
            import boto3

            self._events = boto3.client("events", region_name=self.region)
        return self._events

    async def publish_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        source: str = "opsmind.engine",
    ) -> str:
        client = self._get_client()
        entry = {
            "EventBusName": self.bus_name,
            "Source": source,
            "DetailType": event_type,
            "Detail": json.dumps(payload),
        }
        resp = await asyncio.to_thread(client.put_events, Entries=[entry])
        entries = resp.get("Entries", [])
        event_id = entries[0].get("EventId", "") if entries else ""
        logger.info(
            "published EventBridge event %s (id=%s, bus=%s)",
            event_type,
            event_id,
            self.bus_name,
        )
        return event_id
