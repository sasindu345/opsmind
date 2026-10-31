"""OpsMind FastAPI entry point.

Mounts API feature routers for logs, webhooks, and incident management.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import PROJECT_ROOT, get_settings
from src.api.routes_applications import router as applications_router
from src.api.routes_copilot import router as copilot_router
from src.api.routes_incidents import router as incidents_router
from src.api.routes_logs import router as logs_router
from src.api.routes_metrics import router as metrics_router
from src.api.routes_monitors import options_router as monitor_options_router
from src.api.routes_monitors import router as monitors_router
from src.api.routes_remediations import router as remediations_router
from src.api.routes_repositories import router as repositories_router
from src.api.routes_webhooks import router as webhooks_router

settings = get_settings()
STATIC_DIR = PROJECT_ROOT / "static"

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("opsmind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(
        "starting %s (env=%s, provider=%s, model=%s)",
        settings.app_name,
        settings.app_env,
        settings.llm_provider.value,
        settings.model_name,
    )
    if reason := settings.missing_llm_credentials():
        logger.warning("LLM analysis will fail: %s", reason)
    if not settings.slack_enabled:
        logger.info("Slack tokens absent — ChatOps listener disabled")

    background_tasks: list[asyncio.Task[None]] = []
    stoppables: list[object] = []

    if "PYTEST_CURRENT_TEST" not in os.environ:
        if settings.synthetic_probes_enabled:
            from src.core.synthetic import SyntheticHealthWorker
            from src.infrastructure.factory import (
                get_application_repository,
                get_incident_repository,
                get_telemetry_store,
            )

            probe_worker = SyntheticHealthWorker(
                get_application_repository(settings),
                get_incident_repository(settings),
                timeout=settings.synthetic_probe_timeout_seconds,
                tripwire=settings.synthetic_probe_tripwire,
                telemetry_store=get_telemetry_store(settings),
            )
            background_tasks.append(asyncio.create_task(probe_worker.run()))
            stoppables.append(probe_worker)
            app.state.synthetic_worker = probe_worker

        if settings.github_polling_enabled:
            from src.core.github_poller import GitHubRepoPoller
            from src.infrastructure.factory import (
                get_repository_link_repository,
                get_secret_manager,
                get_telemetry_store,
            )

            github_poller = GitHubRepoPoller(
                get_repository_link_repository(settings),
                get_telemetry_store(settings),
                get_secret_manager(settings),
                settings=settings,
            )
            background_tasks.append(asyncio.create_task(github_poller.run()))
            stoppables.append(github_poller)
            app.state.github_poller = github_poller

        # Without this the queue that webhooks and /analyze/logs/async write to
        # is never drained, so no incident is ever produced from an ingested event.
        from src.core.worker import IncidentWorker

        incident_worker = IncidentWorker(settings=settings)
        background_tasks.append(
            asyncio.create_task(
                incident_worker.run_loop(poll_interval=settings.worker_poll_interval_seconds)
            )
        )
        stoppables.append(incident_worker)
        app.state.incident_worker = incident_worker
        logger.info("incident worker started (queue=%s)", type(incident_worker.queue).__name__)

    yield

    for stoppable in stoppables:
        stoppable.stop()
    for task in background_tasks:
        task.cancel()
    for task in background_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("shutting down %s", settings.app_name)


app = FastAPI(
    title="OpsMind",
    description="AI-driven SRE incident triage engine.",
    version="0.1.0",
    lifespan=lifespan,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(logs_router)
app.include_router(webhooks_router)
app.include_router(incidents_router)
app.include_router(applications_router)
app.include_router(metrics_router)
app.include_router(remediations_router)
app.include_router(monitors_router)
app.include_router(monitor_options_router)
app.include_router(repositories_router)
app.include_router(copilot_router)


@app.get("/api/v1/session", tags=["system"])
async def session_info() -> dict[str, object]:
    """Tell the dashboard whether it must ask the user for an API key.

    Intentionally unauthenticated: the dashboard needs this answer before it can
    know to prompt for credentials.
    """
    return {
        "auth_required": settings.auth_required,
        "app_env": settings.app_env,
        "deployment_mode": settings.deployment_mode.value,
        "remediation_execution_enabled": settings.remediation_execution_enabled,
    }


@app.get("/", tags=["dashboard"])
@app.get("/dashboard", tags=["dashboard"])
async def serve_dashboard() -> FileResponse:
    """Serve the interactive OpsMind Web Dashboard."""
    index_file = STATIC_DIR / "index.html"
    return FileResponse(index_file)


@app.get("/healthz", tags=["system"])
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/readyz", tags=["system"])
async def readyz() -> dict[str, object]:
    """Readiness probe: reports which subsystems are configured."""
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "llm": {
            "provider": settings.llm_provider.value,
            "model": settings.model_name,
            "configured": settings.missing_llm_credentials() is None,
        },
        "slack_enabled": settings.slack_enabled,
        "reports_dir": str(settings.reports_dir),
    }
