import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from typer.testing import CliRunner

from config.settings import get_settings
from src.cli.opsmind_cli import app
from src.infrastructure.interfaces import IncidentRecord
from tests.test_llm_schemas import VALID_ANALYSIS, FakeCompletion

runner = CliRunner()


def test_cli_triage_command(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.llm.client.litellm.acompletion",
        FakeCompletion(json.dumps(VALID_ANALYSIS)),
    )
    get_settings.cache_clear()
    monkeypatch.setattr(get_settings(), "reports_dir", tmp_path)

    result = runner.invoke(app, ["triage", "--service", "checkout"])
    assert result.exit_code == 0
    assert "OpsMind Triage Initiated" in result.stdout
    assert "Incident Analysis Verdict" in result.stdout


def test_cli_incidents_list(monkeypatch):
    mock_repo = MagicMock()
    sample_rec = IncidentRecord(
        incident_id="cli-inc-1",
        service="payment-api",
        environment="production",
        severity="critical",
        status="open",
        created_at=datetime.now(UTC),
        title="Payment gateway timeout",
        probable_cause="Downstream bank gateway failure",
        confidence=0.92,
    )
    mock_repo.list_incidents = AsyncMock(return_value=[sample_rec])
    monkeypatch.setattr(
        "src.cli.opsmind_cli.get_incident_repository",
        lambda settings=None: mock_repo,
    )

    result = runner.invoke(app, ["incidents"])
    assert result.exit_code == 0
    assert "payment-api" in result.stdout
    assert "CRITICAL" in result.stdout


def test_cli_explain_incident(monkeypatch):
    mock_repo = MagicMock()
    sample_rec = IncidentRecord(
        incident_id="cli-inc-2",
        service="auth-service",
        environment="production",
        severity="medium",
        status="acknowledged",
        created_at=datetime.now(UTC),
        title="Token validation slowdown",
        probable_cause="Redis cache high latency",
        confidence=0.85,
        timeline_json=[
            {
                "timestamp": "2026-09-08T10:00:00Z",
                "source": "metric",
                "description": "Latency > 500ms",
            }
        ],
    )
    mock_repo.get_incident = AsyncMock(return_value=sample_rec)
    monkeypatch.setattr(
        "src.cli.opsmind_cli.get_incident_repository",
        lambda settings=None: mock_repo,
    )

    result = runner.invoke(app, ["explain", "cli-inc-2"])
    assert result.exit_code == 0
    assert "Redis cache high latency" in result.stdout
    assert "Latency > 500ms" in result.stdout
