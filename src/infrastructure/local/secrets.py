"""Local secret manager reading from environment variables."""

from __future__ import annotations

import os

from config.settings import Settings, get_settings


class LocalSecretManager:
    """Reads secrets from local environment or settings."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def get_secret(self, secret_name: str) -> str | None:
        return os.environ.get(secret_name)
