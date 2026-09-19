"""Statistical anomaly detection on time-series telemetry.

Provides rolling-window Z-score and Interquartile Range (IQR) detection.
Designed for low-latency in-memory computation on metrics like
CPU utilization, memory usage, request latency, and HTTP error rates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class AnomalyMethod(StrEnum):
    ZSCORE = "zscore"
    IQR = "iqr"


@dataclass(frozen=True)
class MetricPoint:
    timestamp: datetime
    value: float


@dataclass(frozen=True)
class AnomalyRecord:
    metric_name: str
    timestamp: datetime
    value: float
    baseline_value: float  # Mean for z-score, median for IQR
    threshold_value: float  # Threshold boundary exceeded
    score: float  # Z-score or IQR distance ratio
    method: AnomalyMethod
    direction: str  # "spike" (high) or "drop" (low)
    is_anomaly: bool


class AnomalyDetector:
    """Detects statistical anomalies across metric series."""

    def __init__(
        self,
        z_threshold: float = 3.0,
        iqr_multiplier: float = 1.5,
        min_samples: int = 5,
    ) -> None:
        self.z_threshold = z_threshold
        self.iqr_multiplier = iqr_multiplier
        self.min_samples = min_samples

    def detect_zscore(
        self,
        metric_name: str,
        series: list[MetricPoint],
        threshold: float | None = None,
    ) -> list[AnomalyRecord]:
        r"""Detect anomalies using rolling Z-Score ($z = (x - \mu) / \sigma$)."""
        threshold = threshold or self.z_threshold
        if len(series) < self.min_samples:
            return []

        raw_values = [p.value for p in series]
        if np is not None:
            values = np.array(raw_values, dtype=np.float64)
            mean = float(np.mean(values))
            std = float(np.std(values))
        else:  # pragma: no cover
            mean = sum(raw_values) / len(raw_values)
            variance = sum((x - mean) ** 2 for x in raw_values) / len(raw_values)
            std = math.sqrt(variance)

        anomalies: list[AnomalyRecord] = []
        if std == 0.0:
            return anomalies

        for point in series:
            score = (point.value - mean) / std
            if abs(score) >= threshold:
                direction = "spike" if score > 0 else "drop"
                limit = mean + (threshold * std) if score > 0 else mean - (threshold * std)
                anomalies.append(
                    AnomalyRecord(
                        metric_name=metric_name,
                        timestamp=point.timestamp,
                        value=point.value,
                        baseline_value=mean,
                        threshold_value=limit,
                        score=float(score),
                        method=AnomalyMethod.ZSCORE,
                        direction=direction,
                        is_anomaly=True,
                    )
                )

        return anomalies

    def detect_iqr(
        self,
        metric_name: str,
        series: list[MetricPoint],
        multiplier: float | None = None,
    ) -> list[AnomalyRecord]:
        """Detect anomalies using Interquartile Range (IQR = Q3 - Q1)."""
        mult = multiplier or self.iqr_multiplier
        if len(series) < self.min_samples:
            return []

        raw_values = sorted(p.value for p in series)
        if np is not None:
            values = np.array(raw_values, dtype=np.float64)
            q25, q50, q75 = np.percentile(values, [25, 50, 75])
        else:  # pragma: no cover
            n = len(raw_values)
            q50 = raw_values[n // 2]
            q25 = raw_values[n // 4]
            q75 = raw_values[(3 * n) // 4]

        iqr = float(q75 - q25)
        if iqr == 0.0:
            return []

        lower_bound = float(q25 - (mult * iqr))
        upper_bound = float(q75 + (mult * iqr))

        anomalies: list[AnomalyRecord] = []
        for point in series:
            if point.value > upper_bound:
                score = (point.value - q50) / iqr
                anomalies.append(
                    AnomalyRecord(
                        metric_name=metric_name,
                        timestamp=point.timestamp,
                        value=point.value,
                        baseline_value=float(q50),
                        threshold_value=float(upper_bound),
                        score=float(score),
                        method=AnomalyMethod.IQR,
                        direction="spike",
                        is_anomaly=True,
                    )
                )
            elif point.value < lower_bound:
                score = (q50 - point.value) / iqr
                anomalies.append(
                    AnomalyRecord(
                        metric_name=metric_name,
                        timestamp=point.timestamp,
                        value=point.value,
                        baseline_value=float(q50),
                        threshold_value=float(lower_bound),
                        score=float(score),
                        method=AnomalyMethod.IQR,
                        direction="drop",
                        is_anomaly=True,
                    )
                )

        return anomalies

    def evaluate_all(
        self,
        metrics: dict[str, list[MetricPoint]],
        method: AnomalyMethod = AnomalyMethod.ZSCORE,
    ) -> list[AnomalyRecord]:
        """Evaluate a map of metric names to series and return all detected anomalies."""
        all_anomalies: list[AnomalyRecord] = []
        for metric_name, points in metrics.items():
            if method == AnomalyMethod.ZSCORE:
                detected = self.detect_zscore(metric_name, points)
            else:
                detected = self.detect_iqr(metric_name, points)
            all_anomalies.extend(detected)

        all_anomalies.sort(key=lambda a: a.timestamp)
        return all_anomalies
