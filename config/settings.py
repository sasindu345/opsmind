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

    # --- API authentication ---
    api_key: str = Field(
        default="",
        description="When set, mutating endpoints require a matching X-API-Key header.",
    )

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

    # --- Remediation ---
    remediation_execution_enabled: bool = Field(
        default=False,
        description=(
            "Execute approved runbooks for real. Off by default so an approval "
            "produces a clearly-labelled simulation until an operator opts in."
        ),
    )

    # --- Incident worker ---
    worker_poll_interval_seconds: float = Field(
        default=0.5,
        gt=0,
        description="Delay between incident queue polls in the background worker.",
    )

    # --- Synthetic probes ---
    synthetic_probes_enabled: bool = True
    synthetic_probe_tripwire: int = Field(default=3, ge=1, le=20)
    synthetic_probe_timeout_seconds: float = 5.0

    @field_validator("reports_dir", "artifacts_dir")
    @classmethod
    def _absolute_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value

    @property
    def is_aws(self) -> bool:
        """True when the application should use AWS-backed providers."""
        return self.deployment_mode is DeploymentMode.AWS

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

    @property
    def auth_required(self) -> bool:
        """True when an API key is configured and mutations must be authenticated."""
        return bool(self.api_key)

    def missing_llm_credentials(self) -> str | None:
        """Return a human-readable reason the LLM is unusable, or ``None``.

        Each provider is validated against what it actually needs, so ``/readyz``
        cannot report a provider as configured when it would fail on first call.
        """
        if self.llm_provider is LLMProvider.GEMINI:
            if not self.gemini_api_key:
                return "LLM_PROVIDER=gemini but GEMINI_API_KEY is empty"
            return None

        if self.llm_provider is LLMProvider.BEDROCK:
            if not self.bedrock_model_id:
                return "LLM_PROVIDER=bedrock but BEDROCK_MODEL_ID is empty"
            if not self.aws_region:
                return "LLM_PROVIDER=bedrock but AWS_REGION is empty"
            try:
                import boto3
            except ImportError:
                return "LLM_PROVIDER=bedrock but boto3 is not installed"
            # Resolves from env, shared config, or instance profile without a network call.
            if boto3.Session().get_credentials() is None:
                return "LLM_PROVIDER=bedrock but no AWS credentials could be resolved"
            return None

        if not self.ollama_base_url:
            return "LLM_PROVIDER=ollama but OLLAMA_BASE_URL is empty"
        if not self.ollama_model:
            return "LLM_PROVIDER=ollama but OLLAMA_MODEL is empty"
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
