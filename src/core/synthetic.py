"""Synthetic HTTP health probes and the consecutive-failure tripwire.

Probes pin the socket to a pre-validated public IP so a DNS rebinding response
cannot redirect the check onto a private address.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit

from src.core.security import SSRFError, SSRFValidator, ValidatedTarget
from src.core.telemetry import TelemetrySignal, correlate_signals
from src.infrastructure.interfaces import (
    ApplicationRecord,
    ApplicationRepository,
    HealthProbeSnapshot,
    IncidentRepository,
)
from src.llm.schemas import (
    AnalysisResult,
    IncidentStatus,
    RootCauseAnalysis,
    Severity,
    SuggestedFix,
    TimelineItemView,
)

logger = logging.getLogger("opsmind.synthetic")

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_TRIPWIRE = 3
MAX_REDIRECTS = 3
MAX_BODY_BYTES = 512 * 1024


@dataclass
class ProbeFetchResult:
    """Minimal HTTP response used by the probe engine."""

    status_code: int
    location: str | None = None
    error: str | None = None


@dataclass
class ProbeOutcome:
    """Result of one application probe, including tripwire side effects."""

    app_id: str
    status: str
    http_status: int
    latency_ms: float
    is_success: bool
    consecutive_failures: int
    resolved_ip: str | None = None
    error: str | None = None
    incident_id: str | None = None
    incident_opened: bool = False
    recovered: bool = False


def probe_incident_id(app_id: str) -> str:
    """Stable incident id so repeat failures update one probe outage."""
    return f"probe-{app_id}"


async def pinned_http_get(
    target: ValidatedTarget,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ProbeFetchResult:
    """GET ``target.url`` by connecting only to ``target.resolved_ip``."""
    parsed = urlsplit(target.url)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    host_header = target.hostname
    if parsed.port and parsed.port not in (80, 443):
        host_header = f"{target.hostname}:{parsed.port}"

    ssl_context = ssl.create_default_context() if target.scheme == "https" else None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                target.resolved_ip,
                target.port,
                ssl=ssl_context,
                server_hostname=target.hostname if ssl_context else None,
            ),
            timeout=timeout,
        )
    except TimeoutError:
        return ProbeFetchResult(
            status_code=0,
            error=f"Connection timeout after {int(timeout * 1000)}ms",
        )
    except OSError as exc:
        return ProbeFetchResult(status_code=0, error=str(exc))

    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        "User-Agent: OpsMind-SyntheticProbe/1.0\r\n"
        "Accept: */*\r\n"
        "Connection: close\r\n\r\n"
    )
    try:
        writer.write(request.encode("ascii", errors="strict"))
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(MAX_BODY_BYTES), timeout=timeout)
    except TimeoutError:
        return ProbeFetchResult(
            status_code=0,
            error=f"Connection timeout after {int(timeout * 1000)}ms",
        )
    except (OSError, UnicodeEncodeError) as exc:
        return ProbeFetchResult(status_code=0, error=str(exc))
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    header_blob = raw.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1", errors="replace")
    lines = header_blob.split("\r\n")
    if not lines or " " not in lines[0]:
        return ProbeFetchResult(status_code=0, error="Malformed HTTP response")
    try:
        status_code = int(lines[0].split(" ", 2)[1])
    except (IndexError, ValueError):
        return ProbeFetchResult(status_code=0, error="Malformed HTTP status line")

    location = None
    for line in lines[1:]:
        if line.lower().startswith("location:"):
            location = line.split(":", 1)[1].strip()
            break
    return ProbeFetchResult(status_code=status_code, location=location)


def _uptime_percent(snapshots: list[HealthProbeSnapshot]) -> float:
    if not snapshots:
        return 100.0
    successes = sum(1 for item in snapshots if item.is_success)
    return round(100.0 * successes / len(snapshots), 2)


async def _open_probe_incident(
    app: ApplicationRecord,
    snapshot: HealthProbeSnapshot,
    incident_repo: IncidentRepository,
    *,
    tripwire: int,
    related_signals: list[TelemetrySignal] | None = None,
) -> tuple[str, bool]:
    incident_id = probe_incident_id(app.app_id)
    existing = await incident_repo.get_incident(incident_id)
    if existing is not None and existing.status not in {
        IncidentStatus.RESOLVED.value,
        IncidentStatus.CLOSED.value,
    }:
        return incident_id, False

    detail = snapshot.error_message or f"HTTP {snapshot.http_status}"
    now = datetime.now(UTC)
    probe_signal = TelemetrySignal(
        signal_id=snapshot.probe_id,
        source="synthetic",
        app_id=app.app_id,
        service=app.app_id,
        environment=app.environment,
        timestamp=snapshot.timestamp,
        level="CRITICAL",
        metric_name="http_probe_latency",
        metric_value=snapshot.latency_ms,
        raw_message=detail,
        metadata={"http_status": snapshot.http_status, "latency_ms": snapshot.latency_ms},
    )
    unified = correlate_signals(
        [probe_signal, *(related_signals or [])],
        app_id=app.app_id,
        incident_time=now,
    )
    evidence = [
        f"HTTP probe failed: status {snapshot.http_status}, latency {snapshot.latency_ms:.0f}ms",
        f"Consecutive failures reached the tripwire ({tripwire}).",
        *unified.evidence,
    ]
    title = (
        unified.title
        if unified.deployment_sha or unified.log_template
        else f"{app.name} is unavailable"
    )
    deduped = list(dict.fromkeys(evidence))
    result = AnalysisResult(
        incident_id=incident_id,
        service=app.app_id,
        environment=app.environment,
        status=IncidentStatus.OPEN,
        created_at=now,
        analysis=RootCauseAnalysis(
            title=title,
            summary=(
                f"{app.name} failed {tripwire} consecutive synthetic health checks. "
                f"Latest result: {detail}."
            ),
            probable_cause=(
                unified.probable_cause
                if unified.deployment_sha or unified.log_template
                else f"Synthetic health probe to {app.health_url} failed repeatedly ({detail})."
            ),
            confidence=0.9,
            severity=Severity.CRITICAL,
            affected_services=[app.app_id],
            evidence=deduped,
            suggested_fixes=[
                SuggestedFix(
                    title="Restart service",
                    description="Roll the service and confirm the health URL returns HTTP 200.",
                    risk=Severity.LOW,
                    runbook_id="restart-service",
                )
            ],
        ),
        observed_evidence=deduped,
        timeline=[
            TimelineItemView(
                timestamp=now,
                source="synthetic",
                event_type="probe_failure",
                description=f"Health check failed: {detail}",
            )
        ],
        model="synthetic-probe",
        degraded=True,
        app_id=app.app_id,
        deployment_sha=unified.deployment_sha,
    )
    await incident_repo.save_incident(result)
    logger.warning("opened synthetic incident %s for %s", incident_id, app.app_id)
    return incident_id, True


async def execute_probe(
    app: ApplicationRecord,
    app_repo: ApplicationRepository,
    incident_repo: IncidentRepository,
    *,
    validator: SSRFValidator | None = None,
    fetch=None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    tripwire: int = DEFAULT_TRIPWIRE,
    telemetry_store=None,
) -> ProbeOutcome:
    """Probe one application, persist the sample, and apply the failure tripwire."""
    validator = validator or SSRFValidator()
    fetch = fetch or pinned_http_get
    if not app.health_url:
        return ProbeOutcome(
            app_id=app.app_id,
            status="skipped",
            http_status=0,
            latency_ms=0.0,
            is_success=False,
            consecutive_failures=app.consecutive_failures,
            error="Application has no configured health_url",
        )

    started = datetime.now(UTC)
    current_url = app.health_url
    resolved_ip: str | None = None
    fetched: ProbeFetchResult | None = None
    for _ in range(MAX_REDIRECTS + 1):
        target = validator.validate_url(current_url)
        resolved_ip = target.resolved_ip
        fetched = await fetch(target, timeout=timeout)
        if fetched.status_code in {301, 302, 303, 307, 308} and fetched.location:
            current_url = urljoin(current_url, fetched.location)
            continue
        break
    assert fetched is not None

    latency_ms = round((datetime.now(UTC) - started).total_seconds() * 1000.0, 2)
    is_success = 200 <= fetched.status_code < 300
    error = fetched.error
    if not is_success and not error:
        error = f"HTTP {fetched.status_code}"

    snapshot = HealthProbeSnapshot(
        probe_id=str(uuid.uuid4()),
        app_id=app.app_id,
        timestamp=datetime.now(UTC),
        http_status=fetched.status_code,
        latency_ms=latency_ms,
        is_success=is_success,
        error_message=None if is_success else error,
        resolved_ip=resolved_ip,
    )
    await app_repo.save_probe_snapshot(snapshot)
    if telemetry_store is not None:
        await telemetry_store.save_signal(
            TelemetrySignal(
                signal_id=snapshot.probe_id,
                source="synthetic",
                app_id=app.app_id,
                service=app.app_id,
                environment=app.environment,
                timestamp=snapshot.timestamp,
                level="INFO" if is_success else "ERROR",
                metric_name="http_probe_latency",
                metric_value=latency_ms,
                raw_message=None if is_success else error,
                metadata={"http_status": fetched.status_code, "latency_ms": latency_ms},
            )
        )

    since = datetime.now(UTC) - timedelta(hours=24)
    history = await app_repo.list_probe_snapshots(app.app_id, since=since, limit=2000)
    uptime = _uptime_percent(history)

    incident_id = None
    incident_opened = False
    recovered = False
    if is_success:
        new_status = "healthy"
        failures = 0
        recovered = app.consecutive_failures > 0 or app.health_status in {"degraded", "critical"}
        if recovered:
            await incident_repo.update_status(
                probe_incident_id(app.app_id),
                IncidentStatus.RESOLVED,
            )
    else:
        failures = app.consecutive_failures + 1
        if failures >= tripwire:
            new_status = "critical"
            related = []
            if telemetry_store is not None:
                related = await telemetry_store.list_signals(
                    app.app_id,
                    since=datetime.now(UTC) - timedelta(minutes=15),
                )
            incident_id, incident_opened = await _open_probe_incident(
                app,
                snapshot,
                incident_repo,
                tripwire=tripwire,
                related_signals=related,
            )
        else:
            new_status = "degraded"

    await app_repo.update_application(
        app.app_id,
        {
            "health_status": new_status,
            "current_latency_ms": latency_ms,
            "consecutive_failures": failures,
            "uptime_24h_percent": uptime,
            "last_probe_at": snapshot.timestamp,
        },
    )
    return ProbeOutcome(
        app_id=app.app_id,
        status=new_status,
        http_status=fetched.status_code,
        latency_ms=latency_ms,
        is_success=is_success,
        consecutive_failures=failures,
        resolved_ip=resolved_ip,
        error=None if is_success else error,
        incident_id=incident_id,
        incident_opened=incident_opened,
        recovered=recovered and is_success,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SyntheticHealthWorker:
    """Background loop that probes registered applications on their interval."""

    def __init__(
        self,
        app_repo: ApplicationRepository,
        incident_repo: IncidentRepository,
        *,
        poll_seconds: float = 5.0,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        tripwire: int = DEFAULT_TRIPWIRE,
        validator: SSRFValidator | None = None,
        fetch=None,
        telemetry_store=None,
    ) -> None:
        self._app_repo = app_repo
        self._incident_repo = incident_repo
        self._poll_seconds = poll_seconds
        self._timeout = timeout
        self._tripwire = tripwire
        self._validator = validator or SSRFValidator()
        self._fetch = fetch
        self._telemetry_store = telemetry_store
        self._stop = asyncio.Event()

    async def run_once(self, now: datetime | None = None) -> list[ProbeOutcome]:
        """Probe every application whose interval has elapsed."""
        moment = now or datetime.now(UTC)
        apps = await self._app_repo.list_applications(limit=500)
        outcomes: list[ProbeOutcome] = []
        for app in apps:
            if not app.health_url:
                continue
            if app.last_probe_at is not None:
                elapsed = (moment - _as_utc(app.last_probe_at)).total_seconds()
                if elapsed < app.probe_interval_seconds:
                    continue
            try:
                outcome = await execute_probe(
                    app,
                    self._app_repo,
                    self._incident_repo,
                    validator=self._validator,
                    fetch=self._fetch,
                    timeout=self._timeout,
                    tripwire=self._tripwire,
                    telemetry_store=self._telemetry_store,
                )
            except SSRFError as exc:
                logger.warning("skipping probe for %s: %s", app.app_id, exc.public_message)
                continue
            outcomes.append(outcome)
        return outcomes

    async def run(self) -> None:
        """Poll until ``stop`` is called."""
        logger.info("synthetic health worker started")
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("synthetic health worker cycle failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                continue
        logger.info("synthetic health worker stopped")

    def stop(self) -> None:
        self._stop.set()


def outcome_to_dict(outcome: ProbeOutcome) -> dict[str, Any]:
    """Serialize a probe outcome for the on-demand probe API."""
    payload: dict[str, Any] = {
        "app_id": outcome.app_id,
        "status": outcome.status,
        "http_status": outcome.http_status,
        "latency_ms": outcome.latency_ms,
        "is_success": outcome.is_success,
        "consecutive_failures": outcome.consecutive_failures,
        "resolved_ip": outcome.resolved_ip,
        "incident_opened": outcome.incident_opened,
        "recovered": outcome.recovered,
    }
    if outcome.error:
        payload["error"] = outcome.error
    if outcome.incident_id:
        payload["incident_id"] = outcome.incident_id
    return payload
