"""OpsMind FastAPI entry point.

Phase 0 exposes only health endpoints; feature routers are mounted here as each
phase lands (see PLAN.md).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import get_settings
from src.api.routes_logs import router as logs_router

settings = get_settings()

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("opsmind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
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


app.include_router(logs_router)


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
