"""Multi-source incident correlator.

Correlates log clusters, metric anomalies, git deployments/commits, and configuration
changes into a unified timeline and ranked root-cause hypotheses.

Crucially enforces three distinct layers:
1. Observed Evidence (Deterministic facts: exact timestamps, log patterns, metric values, SHAs)
2. Inferred Correlation (Deterministic ranking via temporal proximity and service affinity)
3. LLM Hypothesis (Probabilistic AI deductions, strictly labeled as hypotheses)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.core.anomaly_detector import AnomalyRecord


@dataclass(frozen=True)
class DeploymentRecord:
    commit_sha: str
    author: str
    service: str
    environment: str
    timestamp: datetime
    message: str
    changed_files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TimelineEntry:
    timestamp: datetime
    source: str  # "git", "metric", "log", "config", "incident"
    event_type: str
    description: str
    is_evidence: bool = True
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CorrelationMatch:
    deployment: DeploymentRecord
    score: float  # 0.0 to 1.0 confidence
    time_delta_seconds: float
    reasons: list[str]


@dataclass
class IncidentCorrelatorResult:
    observed_evidence: list[str]
    timeline: list[TimelineEntry]
    correlated_deployments: list[CorrelationMatch]
    inferred_cause_summary: str


class IncidentCorrelator:
    """Correlates multi-source telemetry around an incident window."""

    def __init__(
        self,
        correlation_window_minutes: int = 15,
    ) -> None:
        self.correlation_window = timedelta(minutes=correlation_window_minutes)

    def build_timeline(
        self,
        incident_time: datetime,
        log_clusters: list[dict[str, object]],
        anomalies: list[AnomalyRecord],
        deployments: list[DeploymentRecord],
    ) -> list[TimelineEntry]:
        """Construct a chronologically ordered, multi-source timeline within the window."""
        timeline: list[TimelineEntry] = []
        window_start = incident_time - self.correlation_window
        window_end = incident_time + timedelta(minutes=5)

        # Add deployments within window
        for dep in deployments:
            if window_start <= dep.timestamp <= window_end:
                timeline.append(
                    TimelineEntry(
                        timestamp=dep.timestamp,
                        source="git",
                        event_type="deployment",
                        description=(
                            f"Deployment {dep.commit_sha[:7]} on {dep.service} by "
                            f"{dep.author}: {dep.message}"
                        ),
                        metadata={
                            "commit_sha": dep.commit_sha,
                            "author": dep.author,
                            "service": dep.service,
                            "changed_files": dep.changed_files,
                        },
                    )
                )

        # Add metric anomalies within window
        for anom in anomalies:
            if window_start <= anom.timestamp <= window_end:
                desc = (
                    f"Metric anomaly on {anom.metric_name}: {anom.direction} to "
                    f"{anom.value:.2f} (baseline {anom.baseline_value:.2f}, "
                    f"score: {anom.score:.2f})"
                )
                timeline.append(
                    TimelineEntry(
                        timestamp=anom.timestamp,
                        source="metric",
                        event_type=f"metric_{anom.direction}",
                        description=desc,
                        metadata={
                            "metric_name": anom.metric_name,
                            "value": anom.value,
                            "score": anom.score,
                        },
                    )
                )

        # Add incident log triage entry
        timeline.append(
            TimelineEntry(
                timestamp=incident_time,
                source="incident",
                event_type="incident_triggered",
                description=f"Incident triage triggered ({len(log_clusters)} log patterns)",
                metadata={"cluster_count": len(log_clusters)},
            )
        )

        timeline.sort(key=lambda t: t.timestamp)
        return timeline

    def correlate(
        self,
        incident_time: datetime,
        service: str,
        log_clusters: list[dict[str, object]],
        anomalies: list[AnomalyRecord] | None = None,
        deployments: list[DeploymentRecord] | None = None,
    ) -> IncidentCorrelatorResult:
        """Run multi-source deterministic correlation."""
        anomalies = anomalies or []
        deployments = deployments or []

        # 1. Observed Evidence Extraction
        evidence: list[str] = []

        for c in log_clusters[:5]:
            template = str(c.get("template", ""))
            count = c.get("occurrences", 1)
            level = c.get("level", "INFO")
            evidence.append(f"[{level}] Log pattern ({count}x): {template}")

        for a in anomalies:
            evidence.append(
                f"[METRIC] {a.metric_name} {a.direction} at {a.timestamp.strftime('%H:%M:%S UTC')} "
                f"(value: {a.value:.2f}, baseline: {a.baseline_value:.2f})"
            )

        # 2. Deployment Correlation Matching
        matches: list[CorrelationMatch] = []
        window_start = incident_time - self.correlation_window
        window_end = incident_time + timedelta(minutes=5)

        for dep in deployments:
            # Check temporal window
            delta = (incident_time - dep.timestamp).total_seconds()
            if not (window_start <= dep.timestamp <= window_end):
                continue

            score = 0.0
            reasons: list[str] = []

            # Service exact match
            if dep.service.lower() == service.lower():
                score += 0.5
                reasons.append(f"Deployment was directly on affected service '{service}'")
            else:
                score += 0.2
                reasons.append(f"Deployment was on neighboring service '{dep.service}'")

            # Temporal proximity (higher if within 10 minutes prior to incident)
            if 0 <= delta <= 600:  # 0 to 10 minutes before
                proximity_score = 0.4 * (1.0 - (delta / 600.0))
                score += proximity_score
                reasons.append(f"Deployed {int(delta // 60)}m before incident onset")
            elif delta > 600:
                score += 0.1
                reasons.append(f"Deployed {int(delta // 60)}m before incident")

            # File pattern affinity (e.g. config/database changes)
            has_config = any(
                "config" in f.lower() or "db" in f.lower() or "sql" in f.lower()
                for f in dep.changed_files
            )
            if has_config:
                score += 0.1
                reasons.append("Deployment included configuration or database schema changes")

            score = min(1.0, score)
            matches.append(
                CorrelationMatch(
                    deployment=dep,
                    score=score,
                    time_delta_seconds=delta,
                    reasons=reasons,
                )
            )

        matches.sort(key=lambda m: m.score, reverse=True)

        # Build Inferred summary
        if matches and matches[0].score >= 0.5:
            top = matches[0]
            inferred_cause = (
                f"Likely correlated with deployment {top.deployment.commit_sha[:7]} on "
                f"'{top.deployment.service}' by {top.deployment.author} ({top.reasons[0]})."
            )
            evidence.append(
                f"[GIT] Deployment {top.deployment.commit_sha[:7]} by {top.deployment.author} "
                f"at {top.deployment.timestamp.strftime('%H:%M:%S UTC')} (score: {top.score:.2f})"
            )
        else:
            inferred_cause = "No high-confidence deployment correlation found in time window."

        # 3. Build Ordered Timeline
        timeline = self.build_timeline(incident_time, log_clusters, anomalies, deployments)

        return IncidentCorrelatorResult(
            observed_evidence=evidence,
            timeline=timeline,
            correlated_deployments=matches,
            inferred_cause_summary=inferred_cause,
        )
