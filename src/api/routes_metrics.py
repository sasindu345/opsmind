"""Application time-series metrics and availability aggregation endpoints."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from config.settings import get_settings
from src.api.schemas import (
    ApplicationMetricsResponse,
    AvailabilitySegment,
    MetricPoint,
)
from src.infrastructure.factory import get_application_repository
from src.infrastructure.interfaces import ApplicationRepository, HealthProbeSnapshot

logger = logging.getLogger("opsmind.api.metrics")

router = APIRouter(prefix="/api/v1/applications", tags=["metrics"])


def _get_repo() -> ApplicationRepository:
    return get_application_repository(get_settings())


RepoDep = Annotated[ApplicationRepository, Depends(_get_repo)]

RANGE_CONFIGS = {
    "1h": {"duration": timedelta(hours=1), "bucket_seconds": 60, "num_segments": 24},
    "6h": {"duration": timedelta(hours=6), "bucket_seconds": 300, "num_segments": 24},
    "24h": {"duration": timedelta(hours=24), "bucket_seconds": 900, "num_segments": 24},
    "7d": {"duration": timedelta(days=7), "bucket_seconds": 3600, "num_segments": 28},
}


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _compute_p95(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = max(0, int(math.ceil(0.95 * len(sorted_vals))) - 1)
    return round(sorted_vals[idx], 2)


@router.get("/{app_id}/metrics", response_model=ApplicationMetricsResponse)
async def get_application_metrics(
    app_id: str,
    repo: RepoDep,
    time_range: str = Query(
        default="24h",
        alias="range",
        description="Time range (1h, 6h, 24h, 7d)",
    ),
) -> ApplicationMetricsResponse:
    """Retrieve aggregated latency and availability metrics for an application."""
    if time_range not in RANGE_CONFIGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid range '{time_range}'. Supported ranges: 1h, 6h, 24h, 7d",
        )

    app = await repo.get_application(app_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )

    cfg = RANGE_CONFIGS[time_range]
    now = datetime.now(UTC)
    since = now - cfg["duration"]
    bucket_sec = cfg["bucket_seconds"]
    num_segments = cfg["num_segments"]

    raw_snapshots = await repo.list_probe_snapshots(app_id=app_id, since=since, limit=5000)

    # Standardize snapshot timestamps
    snapshots: list[HealthProbeSnapshot] = []
    for s in raw_snapshots:
        s.timestamp = _ensure_utc(s.timestamp)
        snapshots.append(s)

    # Global summary statistics
    total_probes = len(snapshots)
    success_count = sum(1 for s in snapshots if s.is_success)
    failure_count = total_probes - success_count
    uptime_percent = round((success_count / total_probes) * 100, 2) if total_probes > 0 else 100.0
    error_rate_percent = round((failure_count / total_probes) * 100, 2) if total_probes > 0 else 0.0

    all_latencies = [s.latency_ms for s in snapshots if s.latency_ms > 0]
    avg_latency = round(sum(all_latencies) / len(all_latencies), 2) if all_latencies else 0.0
    p95_latency = _compute_p95(all_latencies)

    # Bucket series calculation
    # Number of buckets from since to now
    total_bucket_count = int(cfg["duration"].total_seconds() // bucket_sec)
    bucket_map: dict[int, list[HealthProbeSnapshot]] = {}
    for s in snapshots:
        offset = (s.timestamp - since).total_seconds()
        b_idx = int(offset // bucket_sec)
        if 0 <= b_idx < total_bucket_count:
            bucket_map.setdefault(b_idx, []).append(s)

    series: list[MetricPoint] = []
    for b_idx in range(total_bucket_count):
        b_time = since + timedelta(seconds=(b_idx * bucket_sec) + (bucket_sec / 2))
        b_snaps = bucket_map.get(b_idx, [])
        if b_snaps:
            b_latencies = [s.latency_ms for s in b_snaps if s.latency_ms > 0]
            b_succ = sum(1 for s in b_snaps if s.is_success)
            b_fail = len(b_snaps) - b_succ
            avg_lat = round(sum(b_latencies) / len(b_latencies), 2) if b_latencies else 0.0
            series.append(
                MetricPoint(
                    timestamp=b_time,
                    avg_latency_ms=avg_lat,
                    min_latency_ms=round(min(b_latencies), 2) if b_latencies else 0.0,
                    max_latency_ms=round(max(b_latencies), 2) if b_latencies else 0.0,
                    p95_latency_ms=_compute_p95(b_latencies),
                    success_count=b_succ,
                    failure_count=b_fail,
                    total_count=len(b_snaps),
                    availability_percent=round((b_succ / len(b_snaps)) * 100, 1),
                )
            )
        else:
            series.append(
                MetricPoint(
                    timestamp=b_time,
                    avg_latency_ms=0.0,
                    min_latency_ms=0.0,
                    max_latency_ms=0.0,
                    p95_latency_ms=0.0,
                    success_count=0,
                    failure_count=0,
                    total_count=0,
                    availability_percent=100.0,
                )
            )

    # Segmented availability calculation
    seg_duration = cfg["duration"].total_seconds() / num_segments
    availability_segments: list[AvailabilitySegment] = []
    for seg_idx in range(num_segments):
        seg_start = since + timedelta(seconds=seg_idx * seg_duration)
        seg_end = seg_start + timedelta(seconds=seg_duration)
        seg_snaps = [s for s in snapshots if seg_start <= s.timestamp < seg_end]

        if not seg_snaps:
            availability_segments.append(
                AvailabilitySegment(
                    timestamp=seg_start,
                    status="nodata",
                    availability_percent=100.0,
                    total_count=0,
                )
            )
        else:
            seg_succ = sum(1 for s in seg_snaps if s.is_success)
            pct = round((seg_succ / len(seg_snaps)) * 100, 1)
            if pct == 100.0:
                seg_status = "healthy"
            elif pct >= 50.0:
                seg_status = "degraded"
            else:
                seg_status = "down"

            availability_segments.append(
                AvailabilitySegment(
                    timestamp=seg_start,
                    status=seg_status,
                    availability_percent=pct,
                    total_count=len(seg_snaps),
                )
            )

    return ApplicationMetricsResponse(
        app_id=app.app_id,
        range=time_range,
        uptime_percent=uptime_percent,
        avg_latency_ms=avg_latency,
        p95_latency_ms=p95_latency,
        error_rate_percent=error_rate_percent,
        total_probes=total_probes,
        series=series,
        availability_segments=availability_segments,
    )
