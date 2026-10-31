"""Local secret manager.

Reads from the environment first so existing configuration keeps working, and
falls back to an owner-readable JSON file for secrets a user supplies at
runtime, such as a GitHub token pasted into the dashboard.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from config.settings import Settings, get_settings

logger = logging.getLogger("opsmind.infrastructure.local_secrets")

# Owner read/write only. These are credentials on a developer machine.
_FILE_MODE = 0o600
_DIR_MODE = 0o700


class LocalSecretManager:
    """Reads secrets from the environment, then from a local secrets file."""

    def __init__(self, settings: Settings | None = None, path: Path | None = None) -> None:
        self.settings = settings or get_settings()
        self.path = Path(path) if path else self.settings.local_secrets_path

    def _read_all(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("could not read local secrets file: %s", exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write_all(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, _DIR_MODE)
        except OSError:
            # Best effort: a restrictive umask or a shared directory may refuse.
            pass
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, _FILE_MODE)
        except OSError:
            logger.warning("could not restrict permissions on %s", self.path)

    async def get_secret(self, secret_name: str) -> str | None:
        env_value = os.environ.get(secret_name)
        if env_value:
            return env_value
        return self._read_all().get(secret_name)

    async def put_secret(self, secret_name: str, value: str) -> None:
        data = self._read_all()
        data[secret_name] = value
        self._write_all(data)
        # Deliberately logs the name only, never the value.
        logger.info("stored local secret %s", secret_name)

    async def delete_secret(self, secret_name: str) -> bool:
        data = self._read_all()
        if secret_name not in data:
            return False
        del data[secret_name]
        self._write_all(data)
        logger.info("deleted local secret %s", secret_name)
        return True
