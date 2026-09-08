"""Slack Bolt application and ChatOps interactive action handlers."""

from __future__ import annotations

import logging
from typing import Any

from config.settings import Settings, get_settings
from src.infrastructure.factory import get_incident_repository
from src.llm.schemas import IncidentStatus

logger = logging.getLogger("opsmind.chatops")


class SlackChatOps:
    """Slack Bolt integration for incident cards and interactive triage."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.app = None
        self.handler = None
        self._init_app()

    def _init_app(self) -> None:
        if not self.settings.slack_enabled:
            logger.info("Slack tokens not configured; ChatOps running in mock/disabled mode.")
            return

        try:
            from slack_bolt.async_app import AsyncApp

            self.app = AsyncApp(token=self.settings.slack_bot_token)
            self._register_handlers()
        except ImportError:
            logger.warning("slack-bolt not installed; Slack listener unavailable.")

    def _register_handlers(self) -> None:
        if not self.app:
            return

        @self.app.action("ack_incident")
        async def handle_ack(ack, body, say):
            await ack()
            inc_id = body.get("actions", [{}])[0].get("value", "")
            user_id = body.get("user", {}).get("id", "unknown")
            repo = get_incident_repository(self.settings)
            await repo.update_status(inc_id, IncidentStatus.ACKNOWLEDGED)
            await say(f"✅ Incident `{inc_id[:8]}` was acknowledged by <@{user_id}>.")

        @self.app.action("explain_incident")
        async def handle_explain(ack, body, say):
            await ack()
            inc_id = body.get("actions", [{}])[0].get("value", "")
            repo = get_incident_repository(self.settings)
            inc = await repo.get_incident(inc_id)
            if not inc:
                await say(f"⚠️ Incident `{inc_id}` not found.")
                return

            timeline_str = "\n".join(
                f"• *{t.get('source', 'log')}* [{t.get('timestamp', '')[:19]}]: "
                f"{t.get('description', '')}"
                for t in inc.timeline_json[:5]
            ) or "_No timeline entries._"

            await say(
                f"📋 *Incident Explanation (`{inc_id[:8]}`)*:\n"
                f"*Service:* `{inc.service}`\n"
                f"*Cause:* {inc.probable_cause}\n\n"
                f"*Timeline:*\n{timeline_str}"
            )

    async def send_incident_notification(
        self,
        blocks: list[dict[str, Any]],
        channel: str | None = None,
    ) -> bool:
        """Post an interactive incident Block Kit card to a Slack channel."""
        if not self.app:
            logger.info("Mock Slack Notification: %d blocks", len(blocks))
            return False

        target_channel = channel or self.settings.slack_default_channel
        try:
            await self.app.client.chat_postMessage(channel=target_channel, blocks=blocks)
            return True
        except Exception as exc:
            logger.error("failed sending Slack message to %s: %s", target_channel, exc)
            return False
