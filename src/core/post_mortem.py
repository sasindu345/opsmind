"""Markdown post-mortem generation."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from config.settings import PROJECT_ROOT, Settings, get_settings
from src.llm.schemas import AnalysisResult

logger = logging.getLogger(__name__)

TEMPLATES_DIR = PROJECT_ROOT / "templates"
TEMPLATE_NAME = "post_mortem.md.jinja2"

_environment = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(default=False),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "incident"


def render_post_mortem(result: AnalysisResult) -> str:
    """Render the Markdown report without writing it to disk."""
    template = _environment.get_template(TEMPLATE_NAME)
    return template.render(result=result, analysis=result.analysis)


def write_post_mortem(result: AnalysisResult, settings: Settings | None = None) -> Path:
    """Render and persist the report, returning its path."""
    settings = settings or get_settings()
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        f"incident-{result.created_at:%Y-%m-%d}"
        f"-{_slugify(result.service)}-{result.incident_id[:8]}.md"
    )
    path = settings.reports_dir / filename
    path.write_text(render_post_mortem(result), encoding="utf-8")
    logger.info("post-mortem written to %s", path)
    return path
