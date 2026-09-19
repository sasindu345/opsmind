from datetime import UTC, datetime, timedelta

from src.core.anomaly_detector import AnomalyMethod, AnomalyRecord
from src.core.correlator import DeploymentRecord, IncidentCorrelator


def test_correlate_matches_recent_deployment_on_same_service():
    correlator = IncidentCorrelator(correlation_window_minutes=15)
    incident_time = datetime(2026, 9, 6, 18, 42, 0, tzinfo=UTC)

    deployments = [
        DeploymentRecord(
            commit_sha="a1b2c3d4e5f6",
            author="alice@example.com",
            service="checkout",
            environment="production",
            timestamp=incident_time - timedelta(minutes=3),  # 18:39
            message="Update database pool size",
            changed_files=["config/db.yaml", "src/pool.py"],
        ),
        DeploymentRecord(
            commit_sha="999999999999",
            author="bob@example.com",
            service="auth",
            environment="production",
            timestamp=incident_time - timedelta(hours=2),  # Outside window
            message="Refactor token parsing",
            changed_files=["src/tokens.py"],
        ),
    ]

    anomalies = [
        AnomalyRecord(
            metric_name="cpu_utilization",
            timestamp=incident_time - timedelta(minutes=2),
            value=95.0,
            baseline_value=30.0,
            threshold_value=70.0,
            score=3.5,
            method=AnomalyMethod.ZSCORE,
            direction="spike",
            is_anomaly=True,
        )
    ]

    log_clusters = [
        {"template": "Connection pool exhausted for DB <IP>", "occurrences": 150, "level": "ERROR"}
    ]

    result = correlator.correlate(
        incident_time=incident_time,
        service="checkout",
        log_clusters=log_clusters,
        anomalies=anomalies,
        deployments=deployments,
    )

    assert len(result.correlated_deployments) == 1
    top = result.correlated_deployments[0]
    assert top.deployment.commit_sha == "a1b2c3d4e5f6"
    assert top.score >= 0.8
    assert "checkout" in result.inferred_cause_summary
    assert any("Connection pool exhausted" in ev for ev in result.observed_evidence)
    assert any("cpu_utilization" in ev for ev in result.observed_evidence)
    assert len(result.timeline) == 3  # deployment, metric spike, incident triage
