"""AWS Secrets Manager client."""

from __future__ import annotations

import asyncio
import logging

from config.settings import Settings, get_settings

logger = logging.getLogger("opsmind.infrastructure.secrets_manager")


class AWSSecretManager:
    """Retrieves credentials securely from AWS Secrets Manager."""

    def __init__(self, region: str | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.region = region or self.settings.aws_region
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("secretsmanager", region_name=self.region)
        return self._client

    async def get_secret(self, secret_name: str) -> str | None:
        client = self._get_client()
        try:
            resp = await asyncio.to_thread(client.get_secret_value, SecretId=secret_name)
            return resp.get("SecretString")
        except Exception as exc:
            logger.warning("failed to fetch secret %s from Secrets Manager: %s", secret_name, exc)
            return None

    async def put_secret(self, secret_name: str, value: str) -> None:
        client = self._get_client()
        try:
            await asyncio.to_thread(
                client.put_secret_value,
                SecretId=secret_name,
                SecretString=value,
            )
        except Exception:
            # The secret does not exist yet, so create it.
            await asyncio.to_thread(
                client.create_secret,
                Name=secret_name,
                SecretString=value,
            )
        # Deliberately logs the name only, never the value.
        logger.info("stored secret %s in Secrets Manager", secret_name)

    async def delete_secret(self, secret_name: str) -> bool:
        client = self._get_client()
        try:
            await asyncio.to_thread(
                client.delete_secret,
                SecretId=secret_name,
                ForceDeleteWithoutRecovery=True,
            )
        except Exception as exc:
            logger.warning("failed to delete secret %s: %s", secret_name, exc)
            return False
        logger.info("deleted secret %s from Secrets Manager", secret_name)
        return True
