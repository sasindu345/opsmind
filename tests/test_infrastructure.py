from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config.settings import DeploymentMode, Settings
from src.infrastructure.aws.repository import DynamoDBIncidentRepository
from src.infrastructure.aws.storage import S3ArtifactStorage
from src.infrastructure.factory import (
    get_artifact_storage,
    get_event_publisher,
    get_incident_repository,
    get_secret_manager,
)
from src.infrastructure.local.events import LocalEventPublisher
from src.infrastructure.local.repository import SQLiteIncidentRepository
from src.infrastructure.local.secrets import LocalSecretManager
from src.infrastructure.local.storage import LocalArtifactStorage
from src.llm.schemas import (
    AnalysisResult,
    IncidentStatus,
    LogClusterView,
    RootCauseAnalysis,
    Severity,
    SuggestedFix,
)


@pytest.fixture
def sample_analysis_result() -> AnalysisResult:
    return AnalysisResult(
        incident_id="inc-test-1234",
        service="checkout",
        environment="production",
        status=IncidentStatus.OPEN,
        created_at=datetime.now(UTC),
        analysis=RootCauseAnalysis(
            title="Database pool exhausted",
            summary="Connections reached limit",
            probable_cause="Too many concurrent checkouts",
            confidence=0.88,
            severity=Severity.HIGH,
            affected_services=["checkout"],
            evidence=["[ERROR] pool full"],
            suggested_fixes=[
                SuggestedFix(
                    title="Scale pool",
                    description="Increase max connections to 50",
                    risk=Severity.LOW,
                )
            ],
        ),
        clusters=[
            LogClusterView(
                template="pool full",
                occurrences=50,
                level="ERROR",
                sample="DB pool full",
            )
        ],
        observed_evidence=["[ERROR] pool full"],
        lines_ingested=100,
        token_reduction=0.9,
    )


@pytest.mark.asyncio
async def test_sqlite_repository_crud(tmp_path: Path, sample_analysis_result: AnalysisResult):
    db_file = tmp_path / "test_opsmind.db"
    repo = SQLiteIncidentRepository(db_path=db_file)

    # 1. Save incident
    inc_id = await repo.save_incident(sample_analysis_result)
    assert inc_id == "inc-test-1234"

    # 2. Get incident
    record = await repo.get_incident("inc-test-1234")
    assert record is not None
    assert record.service == "checkout"
    assert record.severity == "high"
    assert record.status == "open"
    assert record.probable_cause == "Too many concurrent checkouts"
    assert len(record.evidence_summary) == 1

    # 3. List incidents
    incidents = await repo.list_incidents(service="checkout")
    assert len(incidents) == 1

    # 4. Update status
    updated = await repo.update_status("inc-test-1234", IncidentStatus.RESOLVED)
    assert updated is True

    resolved_rec = await repo.get_incident("inc-test-1234")
    assert resolved_rec is not None
    assert resolved_rec.status == "resolved"
    assert resolved_rec.resolved_at is not None


@pytest.mark.asyncio
async def test_local_artifact_storage(tmp_path: Path):
    storage = LocalArtifactStorage(base_dir=tmp_path)

    key = "incidents/2026/09/postmortem-123.md"
    content = "# Incident Postmortem\n\nDatabase pool exhausted."

    path = await storage.store_artifact(key, content)
    assert Path(path).exists()

    fetched = await storage.get_artifact(key)
    assert fetched == content

    url = await storage.generate_presigned_url(key)
    assert url.startswith("file://")


@pytest.mark.asyncio
async def test_local_event_publisher_and_secrets(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "super-secret-value")
    publisher = LocalEventPublisher()
    secret_mgr = LocalSecretManager()

    event_id = await publisher.publish_event(
        event_type="app.alert",
        payload={"service": "payment", "message": "High error rate"},
    )
    assert event_id != ""

    secret_val = await secret_mgr.get_secret("TEST_KEY")
    assert secret_val == "super-secret-value"


@pytest.mark.asyncio
async def test_dynamodb_repository_with_mock(monkeypatch, sample_analysis_result: AnalysisResult):
    repo = DynamoDBIncidentRepository(table_name="mock-table", region="us-east-1")
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {
            "incident_id": "inc-test-1234",
            "service": "checkout",
            "environment": "production",
            "severity": "high",
            "status": "open",
            "created_at": datetime.now(UTC).isoformat(),
            "title": "Database pool exhausted",
            "probable_cause": "Too many checkouts",
            "confidence": 0.88,
        }
    }
    monkeypatch.setattr(repo, "_get_table", lambda: mock_table)

    inc_id = await repo.save_incident(sample_analysis_result)
    assert inc_id == "inc-test-1234"
    assert mock_table.put_item.called

    record = await repo.get_incident("inc-test-1234")
    assert record is not None
    assert record.service == "checkout"


@pytest.mark.asyncio
async def test_s3_artifact_storage_with_mock(monkeypatch):
    storage = S3ArtifactStorage(bucket_name="mock-bucket", region="us-east-1")
    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.return_value = (
        "https://mock-bucket.s3.amazonaws.com/test.md?sig=123"
    )
    monkeypatch.setattr(storage, "_get_client", lambda: mock_s3)

    uri = await storage.store_artifact("test.md", "# Test Content")
    assert uri == "s3://mock-bucket/test.md"
    assert mock_s3.put_object.called

    url = await storage.generate_presigned_url("test.md")
    assert "https://" in url


def test_factory_resolves_local_providers():
    settings = Settings(deployment_mode=DeploymentMode.LOCAL)
    repo = get_incident_repository(settings)
    storage = get_artifact_storage(settings)
    events = get_event_publisher(settings)
    secrets = get_secret_manager(settings)

    assert isinstance(repo, SQLiteIncidentRepository)
    assert isinstance(storage, LocalArtifactStorage)
    assert isinstance(events, LocalEventPublisher)
    assert isinstance(secrets, LocalSecretManager)
