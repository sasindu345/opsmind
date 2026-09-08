from datetime import UTC, datetime

from src.chatops.block_builder import build_incident_card
from src.infrastructure.interfaces import IncidentRecord


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
