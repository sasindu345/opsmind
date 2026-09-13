"""OpsMind FastAPI entry point.

Mounts API feature routers for logs, webhooks, and incident management.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import PROJECT_ROOT, get_settings
from src.api.routes_applications import router as applications_router
from src.api.routes_incidents import router as incidents_router
from src.api.routes_logs import router as logs_router
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
    yield
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
