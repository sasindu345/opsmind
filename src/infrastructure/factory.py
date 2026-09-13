"""Dependency injection factory for infrastructure providers."""

from __future__ import annotations

from config.settings import DeploymentMode, Settings, get_settings
from src.infrastructure.aws.events import AWSEventPublisher
from src.infrastructure.aws.repository import (
    DynamoDBApplicationRepository,
    DynamoDBIncidentRepository,
)
from src.infrastructure.aws.secrets import AWSSecretManager
from src.infrastructure.aws.storage import S3ArtifactStorage
from src.infrastructure.interfaces import (
    ApplicationRepository,
    ArtifactStorage,
    EventPublisher,
    IncidentRepository,
    SecretManager,
)
from src.infrastructure.local.events import LocalEventPublisher
from src.infrastructure.local.repository import (
    SQLiteApplicationRepository,
    SQLiteIncidentRepository,
)
from src.infrastructure.local.secrets import LocalSecretManager
from src.infrastructure.local.storage import LocalArtifactStorage


def get_application_repository(settings: Settings | None = None) -> ApplicationRepository:
    """Return application repository implementation based on configured deployment mode."""
    settings = settings or get_settings()
    if settings.deployment_mode == DeploymentMode.AWS:
        return DynamoDBApplicationRepository(settings=settings)
    return SQLiteApplicationRepository(settings=settings)


def get_incident_repository(settings: Settings | None = None) -> IncidentRepository:
    """Return repository implementation based on configured deployment mode."""
    settings = settings or get_settings()
    if settings.deployment_mode == DeploymentMode.AWS:
        return DynamoDBIncidentRepository(settings=settings)
    return SQLiteIncidentRepository(settings=settings)


def get_artifact_storage(settings: Settings | None = None) -> ArtifactStorage:
    """Return artifact storage implementation based on configured deployment mode."""
    settings = settings or get_settings()
    if settings.deployment_mode == DeploymentMode.AWS:
        return S3ArtifactStorage(settings=settings)
    return LocalArtifactStorage(settings=settings)


def get_event_publisher(settings: Settings | None = None) -> EventPublisher:
    """Return event publisher implementation based on configured deployment mode."""
    settings = settings or get_settings()
    if settings.deployment_mode == DeploymentMode.AWS:
        return AWSEventPublisher(settings=settings)
    return LocalEventPublisher()


def get_secret_manager(settings: Settings | None = None) -> SecretManager:
    """Return secret manager implementation based on configured deployment mode."""
    settings = settings or get_settings()
    if settings.deployment_mode == DeploymentMode.AWS:
        return AWSSecretManager(settings=settings)
    return LocalSecretManager(settings=settings)
