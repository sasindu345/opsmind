"""S3 artifact storage with SSE encryption and presigned URLs."""

from __future__ import annotations

import asyncio
import logging

from config.settings import Settings, get_settings

logger = logging.getLogger("opsmind.infrastructure.s3")


class S3ArtifactStorage:
    """Stores incident artifacts (postmortems, logs, evidence) in Amazon S3."""

    def __init__(
        self,
        bucket_name: str | None = None,
        region: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.bucket_name = bucket_name or self.settings.s3_bucket_name
        self.region = region or self.settings.aws_region
        self._s3 = None

    def _get_client(self):
        if self._s3 is None:
            import boto3

            self._s3 = boto3.client("s3", region_name=self.region)
        return self._s3

    async def store_artifact(
        self,
        key: str,
        content: str | bytes,
        content_type: str = "text/markdown",
    ) -> str:
        """Upload an artifact to S3 with AES256 server-side encryption."""
        client = self._get_client()
        body = content.encode("utf-8") if isinstance(content, str) else content

        await asyncio.to_thread(
            client.put_object,
            Bucket=self.bucket_name,
            Key=key,
            Body=body,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        uri = f"s3://{self.bucket_name}/{key}"
        logger.info("stored S3 artifact at %s (size=%d bytes)", uri, len(body))
        return uri

    async def get_artifact(self, key: str) -> str | bytes:
        client = self._get_client()
        resp = await asyncio.to_thread(
            client.get_object,
            Bucket=self.bucket_name,
            Key=key,
        )
        body = resp["Body"].read()
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return body

    async def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a secure, time-limited presigned URL for downloading the artifact."""
        client = self._get_client()
        url = await asyncio.to_thread(
            client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )
        return str(url)
