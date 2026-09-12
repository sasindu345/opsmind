"""Application configuration.

Every environment-driven value lives here. Modules import ``get_settings()``
rather than reading ``os.environ`` directly, so configuration stays in one place
and is trivially overridable in tests.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class DeploymentMode(StrEnum):
    LOCAL = "local"
    AWS = "aws"


class LLMProvider(StrEnum):
    GEMINI = "gemini"
    OLLAMA = "ollama"
    BEDROCK = "bedrock"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Mode ---
    deployment_mode: DeploymentMode = DeploymentMode.LOCAL

    # --- App ---
    app_name: str = "OpsMind"
    app_env: str = "development"
    log_level: str = "INFO"
    reports_dir: Path = Path("reports")
    artifacts_dir: Path = Path("artifacts")

    # --- LLM ---
    llm_provider: LLMProvider = LLMProvider.GEMINI
    gemini_api_key: str = ""
    gemini_model: str = "gemini/gemini-2.0-flash"
    ollama_model: str = "ollama/llama3:8b"
    ollama_base_url: str = "http://localhost:11434"
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    llm_timeout_seconds: int = 60
    llm_max_rpm: int = Field(default=15, description="Free-tier request budget per minute.")

    # --- AWS Configuration ---
    aws_region: str = "us-east-1"
    sqs_queue_url: str = ""
    sqs_dlq_url: str = ""
    eventbridge_bus_name: str = "default"
    dynamodb_table_name: str = "opsmind-incidents"
    s3_bucket_name: str = "opsmind-artifacts"
    secrets_manager_secret_id: str = ""
    cloudwatch_namespace: str = "OpsMind"

    # --- Slack ---
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_default_channel: str = "#incidents"

    # --- Storage (Local) ---
    database_url: str = "sqlite:///./opsmind.db"

    # --- Metrics ---
    prometheus_url: str = "http://localhost:9090"

    # --- GitHub ---
    github_webhook_secret: str = ""

    @field_validator("reports_dir", "artifacts_dir")
    @classmethod
    def _absolute_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value

    @property
    def model_name(self) -> str:
        """The LiteLLM model identifier for the configured provider."""
        if self.llm_provider is LLMProvider.GEMINI:
            return self.gemini_model
        if self.llm_provider is LLMProvider.BEDROCK:
            return f"bedrock/{self.bedrock_model_id}"
        return self.ollama_model

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_bot_token and self.slack_app_token)

    def missing_llm_credentials(self) -> str | None:
        """Return a human-readable reason the LLM is unusable, or ``None``."""
        if self.llm_provider is LLMProvider.GEMINI and not self.gemini_api_key:
            return "LLM_PROVIDER=gemini but GEMINI_API_KEY is empty"
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
