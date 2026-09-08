"""Telemetry metrics and log sanitization.

Emits structured custom metrics for OpsMind operations (incidents, LLM calls, queue times)
and sanitizes sensitive tokens, keys, and credentials from logs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("opsmind.metrics")

_KV_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|password|auth|credential)[\"']?\s*[:=]\s*[\"']?([a-zA-Z0-9_\-\.]{8,})[\"']?",
    re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE)
_AWS_KEY_PATTERN = re.compile(r"AKIA[0-9A-Z]{16}", re.IGNORECASE)
_GH_TOKEN_PATTERN = re.compile(r"ghp_[a-zA-Z0-9]{36}", re.IGNORECASE)


def sanitize_text(text: str) -> str:
    """Mask credentials, tokens, and secret patterns from text before logging or storing."""
    sanitized = _KV_SECRET_PATTERN.sub(r"\1=[REDACTED]", text)
    sanitized = _BEARER_PATTERN.sub("Bearer [REDACTED]", sanitized)
    sanitized = _AWS_KEY_PATTERN.sub("[REDACTED_AWS_KEY]", sanitized)
    sanitized = _GH_TOKEN_PATTERN.sub("[REDACTED_GH_TOKEN]", sanitized)
    return sanitized


@dataclass
class MetricDatum:
    name: str
    value: float
    unit: str = "Count"  # "Count", "Milliseconds", "Percent", "Seconds"
    dimensions: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "MetricName": self.name,
            "Value": self.value,
            "Unit": self.unit,
            "Dimensions": [{"Name": k, "Value": v} for k, v in self.dimensions.items()],
            "Timestamp": self.timestamp.isoformat(),
        }


class MetricsCollector:
    """Collects and publishes internal OpsMind operational metrics."""

    def __init__(self, namespace: str = "OpsMind") -> None:
        self.namespace = namespace
        self._buffer: list[MetricDatum] = []

    def record_incident_detected(self, service: str, severity: str = "high") -> MetricDatum:
        metric = MetricDatum(
            name="opsmind.incidents.detected",
            value=1.0,
            unit="Count",
            dimensions={"Service": service, "Severity": severity},
        )
        self._buffer.append(metric)
        logger.info("metric emitted: %s (+1, service=%s)", metric.name, service)
        return metric

    def record_incident_resolved(self, service: str) -> MetricDatum:
        metric = MetricDatum(
            name="opsmind.incidents.resolved",
            value=1.0,
            unit="Count",
            dimensions={"Service": service},
        )
        self._buffer.append(metric)
        logger.info("metric emitted: %s (+1, service=%s)", metric.name, service)
        return metric

    def record_llm_request(self, model: str, success: bool = True) -> MetricDatum:
        name = "opsmind.llm.requests" if success else "opsmind.llm.failures"
        metric = MetricDatum(
            name=name,
            value=1.0,
            unit="Count",
            dimensions={"Model": model, "Status": "Success" if success else "Failure"},
        )
        self._buffer.append(metric)
        return metric

    def record_queue_processing_time(
        self, duration_seconds: float, queue_name: str = "default"
    ) -> MetricDatum:
        metric = MetricDatum(
            name="opsmind.queue.processing_time",
            value=duration_seconds,
            unit="Seconds",
            dimensions={"Queue": queue_name},
        )
        self._buffer.append(metric)
        return metric

    def record_anomaly_detected(self, metric_name: str, score: float) -> MetricDatum:
        metric = MetricDatum(
            name="opsmind.anomaly.detected",
            value=1.0,
            unit="Count",
            dimensions={"Metric": metric_name},
        )
        self._buffer.append(metric)
        return metric

    def flush(self) -> list[MetricDatum]:
        """Return buffered metrics and clear buffer."""
        flushed = list(self._buffer)
        self._buffer.clear()
        return flushed


_GLOBAL_METRICS = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    return _GLOBAL_METRICS
