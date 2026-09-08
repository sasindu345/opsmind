"""Local filesystem artifact storage for reports, logs, and evidence."""

from __future__ import annotations

import logging
from pathlib import Path

from config.settings import Settings, get_settings

logger = logging.getLogger("opsmind.infrastructure.local_storage")


class LocalArtifactStorage:
    """Stores incident artifacts in local filesystem directories (Zero-AWS)."""

    def __init__(
        self, base_dir: Path | str | None = None, settings: Settings | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.base_dir = Path(base_dir or self.settings.artifacts_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def store_artifact(
        self,
        key: str,
        content: str | bytes,
        content_type: str = "text/markdown",
    ) -> str:
        """Save artifact to disk and return absolute path."""
        target_path = self.base_dir / key
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(content, str):
            target_path.write_text(content, encoding="utf-8")
        else:
            target_path.write_bytes(content)

        logger.info("stored local artifact at %s (%s)", target_path, content_type)
        return str(target_path)

    async def get_artifact(self, key: str) -> str | bytes:
        target_path = self.base_dir / key
        if not target_path.exists():
            raise FileNotFoundError(f"Artifact not found: {key}")
        try:
            return target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return target_path.read_bytes()

    async def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """In local mode, return file path."""
        target_path = self.base_dir / key
        return f"file://{target_path.resolve()}"
