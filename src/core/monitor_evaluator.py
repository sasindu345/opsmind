"""Evaluation of user-configured metric monitors.

A monitor watches one signal that OpsMind already measures with its own synthetic
probes, so a user can configure alerting without deploying Prometheus. Threshold
mode is a plain comparison; anomaly mode delegates to the existing
``AnomalyDetector`` rather than reimplementing the statistics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from config.settings import Settings, get_settings
from src.core.anomaly_detector import AnomalyDetector, MetricPoint
from src.infrastructure.interfaces import HealthProbeSnapshot, MetricMonitorRecord

logger = logging.getLogger("opsmind.monitor")

COMPARATORS = {
    "gt": lambda value, limit: value > limit,
    "gte": lambda value, limit: value >= limit,
    "lt": lambda value, limit: value < limit,
    "lte": lambda value, limit: value <= limit,
}

COMPARISON_WORDS = {
    "gt": "above",
    "gte": "at or above",
    "lt": "below",
    "lte": "at or below",
}

SIGNAL_LABELS = {
    "probe_latency": ("response time", "ms"),
    "probe_error_rate": ("error rate", "%"),
    "probe_availability": ("availability", "%"),
}


@dataclass
class MonitorBreach:
    """A monitor evaluation that crossed its configured condition."""

    monitor_id: str
    app_id: str
    monitor_name: str
    signal_source: str
    mode: str
    observed_value: float
    threshold_value: float
    severity: str
    sample_count: int
    detected_at: datetime
    summary: str

    @property
    def plain_summary(self) -> str:
        return self.summary


def _window_samples(
    snapshots: list[HealthProbeSnapshot],
    window_seconds: int,
    now: datetime,
) -> list[HealthProbeSnapshot]:
    cutoff = now - timedelta(seconds=window_seconds)
    inside: list[HealthProbeSnapshot] = []
    for snapshot in snapshots:
        stamp = snapshot.timestamp
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        if stamp >= cutoff:
            inside.append(snapshot)
    return inside


def _series(
    monitor: MetricMonitorRecord,
    samples: list[HealthProbeSnapshot],
) -> list[MetricPoint]:
    """Project probe samples onto the signal the monitor watches."""
    if monitor.signal_source == "probe_latency":
        return [MetricPoint(timestamp=s.timestamp, value=s.latency_ms) for s in samples]
    if monitor.signal_source == "probe_error_rate":
        return [
            MetricPoint(timestamp=s.timestamp, value=0.0 if s.is_success else 100.0)
            for s in samples
        ]
    if monitor.signal_source == "probe_availability":
        return [
            MetricPoint(timestamp=s.timestamp, value=100.0 if s.is_success else 0.0)
            for s in samples
        ]
    logger.warning(
        "monitor %s has unknown signal_source %s", monitor.monitor_id, monitor.signal_source
    )
    return []


def _aggregate(monitor: MetricMonitorRecord, series: list[MetricPoint]) -> float:
    """Reduce the window to the single number the condition is tested against."""
    values = [point.value for point in series]
    if monitor.signal_source == "probe_latency":
        # Latest sample: a threshold on response time is about right now.
        return values[-1]
    # Rates and availability are only meaningful across the window.
    return sum(values) / len(values)


def evaluate_monitor(
    monitor: MetricMonitorRecord,
    snapshots: list[HealthProbeSnapshot],
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> MonitorBreach | None:
    """Return a breach when the monitor's condition is met, otherwise ``None``.

    Pure: callers own persistence and incident creation, which keeps this
    testable without a database.
    """
    if not monitor.enabled:
        return None

    settings = settings or get_settings()
    moment = now or datetime.now(UTC)

    samples = _window_samples(snapshots, monitor.window_seconds, moment)
    if len(samples) < max(monitor.min_samples, 1):
        return None

    # Oldest first, so "latest" and the statistics agree on ordering.
    samples.sort(key=lambda s: s.timestamp)
    series = _series(monitor, samples)
    if not series:
        return None

    if monitor.mode == "anomaly":
        detector = AnomalyDetector(
            z_threshold=settings.monitor_zscore_threshold,
            iqr_multiplier=settings.monitor_iqr_multiplier,
            min_samples=monitor.min_samples,
        )
        if monitor.anomaly_method == "iqr":
            anomalies = detector.detect_iqr(monitor.signal_source, series)
        else:
            anomalies = detector.detect_zscore(monitor.signal_source, series)
        if not anomalies:
            return None
        worst = max(anomalies, key=lambda a: abs(a.score))
        label, unit = SIGNAL_LABELS.get(monitor.signal_source, (monitor.signal_source, ""))
        return MonitorBreach(
            monitor_id=monitor.monitor_id,
            app_id=monitor.app_id,
            monitor_name=monitor.name,
            signal_source=monitor.signal_source,
            mode=monitor.mode,
            observed_value=worst.value,
            threshold_value=worst.threshold_value,
            severity=monitor.severity,
            sample_count=len(series),
            detected_at=moment,
            summary=(
                f"{label.capitalize()} showed an unusual {worst.direction} to "
                f"{worst.value:.0f}{unit}, against a recent normal of "
                f"{worst.baseline_value:.0f}{unit}."
            ),
        )

    comparator = COMPARATORS.get(monitor.comparison)
    if comparator is None:
        logger.warning(
            "monitor %s has unknown comparison %s", monitor.monitor_id, monitor.comparison
        )
        return None

    observed = _aggregate(monitor, series)
    if not comparator(observed, monitor.threshold_value):
        return None

    label, unit = SIGNAL_LABELS.get(monitor.signal_source, (monitor.signal_source, ""))
    word = COMPARISON_WORDS.get(monitor.comparison, monitor.comparison)
    return MonitorBreach(
        monitor_id=monitor.monitor_id,
        app_id=monitor.app_id,
        monitor_name=monitor.name,
        signal_source=monitor.signal_source,
        mode=monitor.mode,
        observed_value=observed,
        threshold_value=monitor.threshold_value,
        severity=monitor.severity,
        sample_count=len(series),
        detected_at=moment,
        summary=(
            f"{label.capitalize()} is {observed:.0f}{unit}, which is {word} the "
            f"configured limit of {monitor.threshold_value:.0f}{unit}."
        ),
    )


def monitor_incident_id(monitor_id: str) -> str:
    """Stable incident id so repeat breaches update one incident."""
    return f"monitor-{monitor_id}"
