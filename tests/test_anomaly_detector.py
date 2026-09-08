from datetime import UTC, datetime, timedelta

from src.core.anomaly_detector import AnomalyDetector, AnomalyMethod, MetricPoint


def test_zscore_detects_spike():
    detector = AnomalyDetector(z_threshold=2.5, min_samples=5)
    base_time = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

    # 10 normal points around 10.0 with small noise, then one massive spike to 100.0
    points = [
        MetricPoint(timestamp=base_time + timedelta(minutes=i), value=10.0 + (i % 2) * 0.1)
        for i in range(10)
    ]
    points.append(MetricPoint(timestamp=base_time + timedelta(minutes=10), value=100.0))

    anomalies = detector.detect_zscore("cpu_utilization", points)
    assert len(anomalies) == 1
    record = anomalies[0]
    assert record.metric_name == "cpu_utilization"
    assert record.value == 100.0
    assert record.direction == "spike"
    assert record.score > 2.5
    assert record.method == AnomalyMethod.ZSCORE


def test_iqr_detects_spike_and_drop():
    detector = AnomalyDetector(iqr_multiplier=1.5, min_samples=6)
    base_time = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

    points = [
        MetricPoint(timestamp=base_time + timedelta(minutes=0), value=50.0),
        MetricPoint(timestamp=base_time + timedelta(minutes=1), value=52.0),
        MetricPoint(timestamp=base_time + timedelta(minutes=2), value=49.0),
        MetricPoint(timestamp=base_time + timedelta(minutes=3), value=51.0),
        MetricPoint(timestamp=base_time + timedelta(minutes=4), value=50.0),
        MetricPoint(timestamp=base_time + timedelta(minutes=5), value=53.0),
        MetricPoint(timestamp=base_time + timedelta(minutes=6), value=120.0),  # Spike
        MetricPoint(timestamp=base_time + timedelta(minutes=7), value=2.0),  # Drop
    ]

    anomalies = detector.detect_iqr("http_latency", points)
    assert len(anomalies) == 2
    directions = {a.direction for a in anomalies}
    assert directions == {"spike", "drop"}


def test_insufficient_samples_returns_empty():
    detector = AnomalyDetector(min_samples=5)
    points = [
        MetricPoint(timestamp=datetime.now(UTC), value=10.0),
        MetricPoint(timestamp=datetime.now(UTC), value=100.0),
    ]
    assert detector.detect_zscore("mem", points) == []
    assert detector.detect_iqr("mem", points) == []
