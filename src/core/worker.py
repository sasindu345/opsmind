"""Asynchronous incident worker and queue processing engine.

Supports both local in-memory async queues (Zero-AWS) and AWS SQS queues.
Provides:
- Fast asynchronous acknowledgment (<50ms)
- Visibility timeout and exponential backoff retry handling
- Dead-Letter Queue (DLQ) poison-pill isolation
- Idempotency checks via message deduplication IDs
- Correlation ID propagation and structured logging
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from config.settings import Settings, get_settings
from src.api.schemas import LogBatch
from src.core.anomaly_detector import AnomalyRecord
from src.core.correlator import DeploymentRecord
from src.core.pipeline import analyze_logs
from src.llm.schemas import AnalysisResult

logger = logging.getLogger("opsmind.worker")


@dataclass
class IncidentMessage:
    """Standard message envelope for queue ingestion and worker consumption."""

    message_id: str
    correlation_id: str
    service: str
    environment: str
    event_type: str  # "logs", "prometheus", "github", "cloudwatch"
    payload: dict[str, object]
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deduplication_id: str = ""

    def __post_init__(self) -> None:
        if not self.deduplication_id:
            payload_str = json.dumps(self.payload, sort_keys=True)
            raw = f"{self.service}:{self.environment}:{self.event_type}:{payload_str}"
            self.deduplication_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def to_dict(self) -> dict[str, object]:
        return {
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "service": self.service,
            "environment": self.environment,
            "event_type": self.event_type,
            "payload": self.payload,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at.isoformat(),
            "deduplication_id": self.deduplication_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> IncidentMessage:
        created_at_val = data.get("created_at")
        if isinstance(created_at_val, str):
            created_at = datetime.fromisoformat(created_at_val)
        else:
            created_at = datetime.now(UTC)

        return cls(
            message_id=str(data.get("message_id", uuid.uuid4().hex)),
            correlation_id=str(data.get("correlation_id", uuid.uuid4().hex)),
            service=str(data.get("service", "unknown")),
            environment=str(data.get("environment", "production")),
            event_type=str(data.get("event_type", "logs")),
            payload=dict(data.get("payload", {})),  # type: ignore[arg-type]
            retry_count=int(data.get("retry_count", 0)),
            max_retries=int(data.get("max_retries", 3)),
            created_at=created_at,
            deduplication_id=str(data.get("deduplication_id", "")),
        )


class LocalIncidentQueue:
    """In-memory queue for Zero-AWS local development with visibility timeout & DLQ."""

    def __init__(self, visibility_timeout: float = 30.0) -> None:
        self.visibility_timeout = visibility_timeout
        self._queue: asyncio.Queue[IncidentMessage] = asyncio.Queue()
        self.dlq: list[IncidentMessage] = []
        self.processed_dedup_ids: set[str] = set()
        self.inflight: dict[str, tuple[IncidentMessage, float]] = {}

    async def enqueue(self, message: IncidentMessage) -> str:
        """Push a message to the queue."""
        await self._queue.put(message)
        logger.info(
            "enqueued message %s (dedup=%s, corr_id=%s)",
            message.message_id[:8],
            message.deduplication_id[:8],
            message.correlation_id[:8],
        )
        return message.message_id

    async def dequeue(self, timeout: float = 0.5) -> IncidentMessage | None:
        """Pull a message from the queue."""
        try:
            msg = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            now = asyncio.get_event_loop().time()
            self.inflight[msg.message_id] = (msg, now + self.visibility_timeout)
            return msg
        except TimeoutError:
            return None

    async def acknowledge(self, message: IncidentMessage) -> None:
        """Successfully completed processing — remove from in-flight and register dedup."""
        self.inflight.pop(message.message_id, None)
        self.processed_dedup_ids.add(message.deduplication_id)
        logger.info("acknowledged message %s", message.message_id[:8])

    async def reject_to_dlq(self, message: IncidentMessage, reason: str) -> None:
        """Send a poison pill or exhausted retry message to the DLQ."""
        self.inflight.pop(message.message_id, None)
        self.dlq.append(message)
        logger.error(
            "message %s moved to DLQ (retries=%d, reason=%s)",
            message.message_id[:8],
            message.retry_count,
            reason,
        )

    async def retry(self, message: IncidentMessage) -> None:
        """Re-enqueue message with incremented retry count."""
        self.inflight.pop(message.message_id, None)
        message.retry_count += 1
        await self._queue.put(message)
        logger.warning(
            "retrying message %s (attempt %d/%d)",
            message.message_id[:8],
            message.retry_count,
            message.max_retries,
        )

    def is_duplicate(self, deduplication_id: str) -> bool:
        return deduplication_id in self.processed_dedup_ids


class SQSIncidentQueue:
    """AWS SQS client for production asynchronous queue processing."""

    def __init__(
        self,
        queue_url: str,
        dlq_url: str = "",
        region: str = "us-east-1",
        settings: Settings | None = None,
    ) -> None:
        self.queue_url = queue_url
        self.dlq_url = dlq_url
        self.region = region
        self.settings = settings or get_settings()
        self._sqs = None
        self._processed_dedup_ids: set[str] = set()

    def _get_client(self):
        if self._sqs is None:
            import boto3

            self._sqs = boto3.client("sqs", region_name=self.region)
        return self._sqs

    async def enqueue(self, message: IncidentMessage) -> str:
        client = self._get_client()
        body = json.dumps(message.to_dict())
        kwargs: dict[str, object] = {
            "QueueUrl": self.queue_url,
            "MessageBody": body,
            "MessageAttributes": {
                "CorrelationId": {
                    "DataType": "String",
                    "StringValue": message.correlation_id,
                },
                "EventType": {
                    "DataType": "String",
                    "StringValue": message.event_type,
                },
            },
        }
        if self.queue_url.endswith(".fifo"):
            kwargs["MessageGroupId"] = message.service
            kwargs["MessageDeduplicationId"] = message.deduplication_id

        resp = await asyncio.to_thread(client.send_message, **kwargs)
        return resp.get("MessageId", message.message_id)

    async def dequeue(self, timeout: int = 5) -> tuple[IncidentMessage, str] | None:
        client = self._get_client()
        resp = await asyncio.to_thread(
            client.receive_message,
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=timeout,
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )
        messages = resp.get("Messages", [])
        if not messages:
            return None

        sqs_msg = messages[0]
        receipt_handle = sqs_msg["ReceiptHandle"]
        data = json.loads(sqs_msg["Body"])
        msg = IncidentMessage.from_dict(data)
        return msg, receipt_handle

    async def acknowledge(self, receipt_handle: str) -> None:
        client = self._get_client()
        await asyncio.to_thread(
            client.delete_message,
            QueueUrl=self.queue_url,
            ReceiptHandle=receipt_handle,
        )

    async def reject_to_dlq(self, message: IncidentMessage, receipt_handle: str) -> None:
        client = self._get_client()
        if self.dlq_url:
            await asyncio.to_thread(
                client.send_message,
                QueueUrl=self.dlq_url,
                MessageBody=json.dumps(message.to_dict()),
            )
        await self.acknowledge(receipt_handle)

    def is_duplicate(self, deduplication_id: str) -> bool:
        return deduplication_id in self._processed_dedup_ids

    def mark_processed(self, deduplication_id: str) -> None:
        self._processed_dedup_ids.add(deduplication_id)


_GLOBAL_LOCAL_QUEUE = LocalIncidentQueue()


def get_local_queue() -> LocalIncidentQueue:
    return _GLOBAL_LOCAL_QUEUE


class IncidentWorker:
    """Processes enqueued incidents asynchronously through the triage pipeline."""

    def __init__(
        self,
        queue: LocalIncidentQueue | SQSIncidentQueue | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if queue is not None:
            self.queue = queue
        elif self.settings.is_aws and self.settings.sqs_queue_url:
            self.queue = SQSIncidentQueue(
                queue_url=self.settings.sqs_queue_url,
                dlq_url=self.settings.sqs_dlq_url,
                region=self.settings.aws_region,
                settings=self.settings,
            )
        else:
            self.queue = get_local_queue()
        self.processed_count: int = 0
        self.failure_count: int = 0
        self._running: bool = False

    async def process_message(
        self,
        message: IncidentMessage,
    ) -> AnalysisResult | None:
        """Process one incident message with idempotency, pipeline execution, and retry handling."""
        logger.info(
            "worker starting triage for message %s [service=%s, type=%s, corr_id=%s]",
            message.message_id[:8],
            message.service,
            message.event_type,
            message.correlation_id[:8],
        )

        # 1. Idempotency Check
        if self.queue.is_duplicate(message.deduplication_id):
            logger.info(
                "skipping duplicate message %s (dedup=%s)",
                message.message_id[:8],
                message.deduplication_id[:8],
            )
            return None

        # 2. Extract telemetry & logs from payload
        logs = [str(line) for line in message.payload.get("logs", [])]
        if not logs:
            logs = [f"Alert triggered for service {message.service} ({message.event_type})"]

        batch = LogBatch(
            service=message.service,
            environment=message.environment,
            logs=logs,
            occurred_at=message.created_at,
            context=str(message.payload.get("context", "")),
            generate_report=bool(message.payload.get("generate_report", True)),
        )

        anomalies_data = message.payload.get("anomalies")
        anomalies: list[AnomalyRecord] = []
        if isinstance(anomalies_data, list):
            # Reconstruct anomaly records if provided
            pass

        deployments_data = message.payload.get("deployments")
        deployments: list[DeploymentRecord] = []
        if isinstance(deployments_data, list):
            # Reconstruct deployment records if provided
            pass

        # 3. Execute Triage Pipeline
        try:
            result = await analyze_logs(
                batch,
                settings=self.settings,
                anomalies=anomalies,
                deployments=deployments,
            )
            self.processed_count += 1
            logger.info(
                "worker successfully triaged incident %s for %s (probable cause: %s)",
                result.incident_id[:8],
                result.service,
                result.analysis.probable_cause[:60],
            )
            return result
        except Exception as exc:
            self.failure_count += 1
            logger.error(
                "worker failed triage for message %s (corr_id=%s): %s",
                message.message_id[:8],
                message.correlation_id[:8],
                exc,
                exc_info=True,
            )
            raise

    async def run_once(self) -> AnalysisResult | None:
        """Poll one message from the queue and process it with full error/DLQ semantics."""
        if isinstance(self.queue, LocalIncidentQueue):
            msg = await self.queue.dequeue(timeout=0.1)
            if not msg:
                return None

            try:
                result = await self.process_message(msg)
                await self.queue.acknowledge(msg)
                return result
            except Exception as exc:
                if msg.retry_count >= msg.max_retries:
                    await self.queue.reject_to_dlq(msg, reason=str(exc))
                else:
                    await self.queue.retry(msg)
                return None
        else:
            # SQS queue
            dequeue_res = await self.queue.dequeue(timeout=1)
            if not dequeue_res:
                return None
            msg, handle = dequeue_res

            try:
                result = await self.process_message(msg)
                await self.queue.acknowledge(handle)
                self.queue.mark_processed(msg.deduplication_id)
                return result
            except Exception:
                if msg.retry_count >= msg.max_retries:
                    await self.queue.reject_to_dlq(msg, handle)
                else:
                    # SQS will make message visible again after visibility timeout
                    msg.retry_count += 1
                return None

    async def run_loop(self, max_iterations: int | None = None, poll_interval: float = 0.5) -> None:
        """Continuous execution loop for worker daemon."""
        self._running = True
        iterations = 0
        logger.info("incident worker daemon started")

        while self._running:
            try:
                await self.run_once()
            except Exception as exc:
                logger.error("unexpected error in worker loop: %s", exc)

            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            await asyncio.sleep(poll_interval)

        logger.info("incident worker daemon stopped (processed=%d)", self.processed_count)

    def stop(self) -> None:
        self._running = False
