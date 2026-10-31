import json
from datetime import UTC, datetime

import pytest

from src.chatops.block_builder import build_incident_card
from src.infrastructure.interfaces import IncidentRecord


def _analysis_result():
    """A minimal persisted incident, as the pipeline would hand it to Slack."""
    return IncidentRecord(
        incident_id="slack-dispatch-1",
        service="checkout-api",
        environment="production",
        severity="high",
        status="open",
        created_at=datetime.now(UTC),
        title="Checkout API is unavailable",
        probable_cause="Connection pool exhausted",
        confidence=0.8,
        evidence_summary=["pool exhausted"],
    )


def test_build_incident_card_structure():
    record = IncidentRecord(
        incident_id="slack-inc-1",
        service="order-service",
        environment="production",
        severity="critical",
        status="open",
        created_at=datetime.now(UTC),
        title="High order drop rate",
        probable_cause="Database write lock timeout",
        confidence=0.89,
        evidence_summary=["[ERROR] Lock timeout after 30s"],
    )

    blocks = build_incident_card(record)
    assert len(blocks) >= 4

    header = blocks[0]
    assert header["type"] == "header"
    assert "High order drop rate" in header["text"]["text"]

    actions = [b for b in blocks if b.get("type") == "actions"]
    assert len(actions) == 1
    buttons = actions[0]["elements"]
    action_ids = [btn["action_id"] for btn in buttons]
    assert "ack_incident" in action_ids
    assert "explain_incident" in action_ids
    assert "remediate_incident" in action_ids


# --- pipeline dispatch -------------------------------------------------------
# slack_app.py was written but imported nowhere, so no incident ever reached
# Slack. These pin the wiring and its failure behaviour.


@pytest.mark.asyncio
async def test_no_slack_dispatch_when_tokens_are_absent(monkeypatch):
    from config.settings import Settings
    from src.core.pipeline import _notify_slack

    sent: list[object] = []
    monkeypatch.setattr(
        "src.chatops.slack_app.SlackChatOps.send_incident_notification",
        lambda self, blocks, channel=None: sent.append(blocks),
    )
    await _notify_slack(_analysis_result(), Settings(slack_bot_token="", slack_app_token=""))
    assert sent == []


@pytest.mark.asyncio
async def test_incident_card_is_dispatched_when_slack_is_configured(monkeypatch):
    from config.settings import Settings
    from src.core.pipeline import _notify_slack

    sent: list[list[dict]] = []

    async def _capture(self, blocks, channel=None):
        sent.append(blocks)
        return True

    monkeypatch.setattr("src.chatops.slack_app.SlackChatOps.send_incident_notification", _capture)
    await _notify_slack(
        _analysis_result(),
        Settings(slack_bot_token="xoxb-test", slack_app_token="xapp-test"),
    )
    assert len(sent) == 1
    assert sent[0], "a non-empty Block Kit payload is expected"


@pytest.mark.asyncio
async def test_slack_failure_never_breaks_triage(monkeypatch):
    """A Slack outage must not fail the incident that was just analysed."""
    from config.settings import Settings
    from src.core.pipeline import _notify_slack

    async def _boom(self, blocks, channel=None):
        raise RuntimeError("slack is down")

    monkeypatch.setattr("src.chatops.slack_app.SlackChatOps.send_incident_notification", _boom)
    await _notify_slack(
        _analysis_result(),
        Settings(slack_bot_token="xoxb-test", slack_app_token="xapp-test"),
    )


def test_card_link_comes_from_settings_not_a_literal(monkeypatch):
    from config.settings import get_settings
    from src.chatops.block_builder import build_incident_card

    monkeypatch.setenv("DASHBOARD_BASE_URL", "https://opsmind.example.com")
    get_settings.cache_clear()
    try:
        rendered = json.dumps(build_incident_card(_analysis_result()))
        assert "https://opsmind.example.com" in rendered
        assert "localhost:8000" not in rendered
    finally:
        get_settings.cache_clear()
