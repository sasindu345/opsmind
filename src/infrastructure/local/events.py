"""Local in-memory event publisher for Zero-AWS development."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.core.worker import IncidentMessage, get_local_queue

logger = logging.getLogger("opsmind.infrastructure.local_events")


class LocalEventPublisher:
    """Publishes events into the local in-memory incident queue."""

    def __init__(self) -> None:
        self.queue = get_local_queue()

    async def publish_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        source: str = "opsmind",
    ) -> str:
        message_id = uuid.uuid4().hex
        correlation_id = str(payload.get("correlation_id", uuid.uuid4().hex))
        service = str(payload.get("service", "default-service"))
        environment = str(payload.get("environment", "production"))

        msg = IncidentMessage(
            message_id=message_id,
            correlation_id=correlation_id,
            service=service,
            environment=environment,
            event_type=event_type,
            payload=payload,
        )

        await self.queue.enqueue(msg)
        logger.info(
            "published local event %s (id=%s, source=%s)",
            event_type,
            message_id[:8],
            source,
        )
        return message_id
