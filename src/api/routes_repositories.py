"""GitHub repository linking endpoints.

A user pastes a repository and a personal access token; OpsMind then tracks
commits for incident correlation and raises an AI-analysed incident when a CI
run fails. The token is stored through ``SecretManager`` and is never returned
by any endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from config.settings import get_settings
from src.api.security import require_api_key
from src.core.github_client import GitHubClient, GitHubError
from src.infrastructure.factory import (
    get_repository_link_repository,
    get_secret_manager,
    get_telemetry_store,
)
from src.infrastructure.interfaces import (
    RepositoryLinkRepository,
    RepositoryRecord,
    repository_id,
    repository_token_secret_ref,
)

router = APIRouter(prefix="/api/v1/repositories", tags=["repositories"])


def _store() -> RepositoryLinkRepository:
    return get_repository_link_repository(get_settings())


StoreDep = Annotated[RepositoryLinkRepository, Depends(_store)]


class RepositoryConnect(BaseModel):
    """Everything needed to link a repository."""

    app_id: str = Field(min_length=1, description="Application this repository builds.")
    owner: str = Field(min_length=1, max_length=100, description="GitHub user or organisation.")
    name: str = Field(min_length=1, max_length=120, description="Repository name.")
    access_token: str = Field(
        min_length=1,
        description="Personal access token with repo read access. Stored, never returned.",
    )
    default_branch: str = Field(default="main", max_length=250)
    poll_interval_seconds: int | None = Field(default=None, ge=30, le=86_400)
    commits_enabled: bool = True
    actions_enabled: bool = True


class RepositoryUpdate(BaseModel):
    app_id: str | None = None
    default_branch: str | None = Field(default=None, max_length=250)
    access_token: str | None = Field(default=None, min_length=1)
    poll_interval_seconds: int | None = Field(default=None, ge=30, le=86_400)
    commits_enabled: bool | None = None
    actions_enabled: bool | None = None


class RepositoryResponse(BaseModel):
    """A linked repository. Deliberately has no token field."""

    repo_id: str
    app_id: str
    owner: str
    name: str
    full_name: str
    default_branch: str
    token_configured: bool
    poll_interval_seconds: int
    commits_enabled: bool
    actions_enabled: bool
    last_commit_sha: str | None
    last_workflow_run_id: int | None
    rate_limit_remaining: int | None
    last_polled_at: str | None
    last_error: str | None
    created_at: str

    @classmethod
    def from_record(cls, record: RepositoryRecord) -> RepositoryResponse:
        return cls(
            repo_id=record.repo_id,
            app_id=record.app_id,
            owner=record.owner,
            name=record.name,
            full_name=record.full_name,
            default_branch=record.default_branch,
            token_configured=bool(record.token_secret_ref),
            poll_interval_seconds=record.poll_interval_seconds,
            commits_enabled=record.commits_enabled,
            actions_enabled=record.actions_enabled,
            last_commit_sha=record.last_commit_sha,
            last_workflow_run_id=record.last_workflow_run_id,
            rate_limit_remaining=record.rate_limit_remaining,
            last_polled_at=record.last_polled_at.isoformat() if record.last_polled_at else None,
            last_error=record.last_error,
            created_at=record.created_at.isoformat(),
        )


async def _require_repo(store: RepositoryLinkRepository, repo_id: str) -> RepositoryRecord:
    record = await store.get_repository(repo_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository link '{repo_id}' not found.",
        )
    return record


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
async def connect_repository(
    payload: RepositoryConnect,
    store: StoreDep,
) -> RepositoryResponse:
    """Link a GitHub repository, verifying the token before storing anything."""
    settings = get_settings()
    repo_id = repository_id(payload.owner, payload.name)
    secret_ref = repository_token_secret_ref(repo_id)

    # Verify first, so a bad token is rejected rather than silently stored.
    try:
        metadata = await GitHubClient(payload.access_token, settings=settings).verify_access(
            payload.owner, payload.name
        )
    except GitHubError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not access {payload.owner}/{payload.name}: {exc}",
        ) from exc

    await get_secret_manager(settings).put_secret(secret_ref, payload.access_token)

    record = RepositoryRecord(
        repo_id=repo_id,
        app_id=payload.app_id,
        owner=payload.owner,
        name=payload.name,
        default_branch=payload.default_branch or metadata["default_branch"],
        token_secret_ref=secret_ref,
        poll_interval_seconds=(
            payload.poll_interval_seconds or settings.github_poll_interval_seconds
        ),
        commits_enabled=payload.commits_enabled,
        actions_enabled=payload.actions_enabled,
    )
    await store.save_repository(record)
    return RepositoryResponse.from_record(record)


@router.get("", response_model=list[RepositoryResponse])
async def list_repositories(
    store: StoreDep,
    app_id: str | None = Query(default=None),
) -> list[RepositoryResponse]:
    """List linked repositories."""
    records = await store.list_repositories(app_id=app_id)
    return [RepositoryResponse.from_record(record) for record in records]


@router.get("/{repo_id}", response_model=RepositoryResponse)
async def get_repository(repo_id: str, store: StoreDep) -> RepositoryResponse:
    """Retrieve one linked repository."""
    return RepositoryResponse.from_record(await _require_repo(store, repo_id))


@router.patch(
    "/{repo_id}",
    response_model=RepositoryResponse,
    dependencies=[Depends(require_api_key)],
)
async def update_repository(
    repo_id: str,
    payload: RepositoryUpdate,
    store: StoreDep,
) -> RepositoryResponse:
    """Change a link's configuration, optionally rotating the token."""
    settings = get_settings()
    record = await _require_repo(store, repo_id)

    updates = payload.model_dump(exclude_none=True)
    new_token = updates.pop("access_token", None)
    if new_token:
        secret_ref = record.token_secret_ref or repository_token_secret_ref(repo_id)
        await get_secret_manager(settings).put_secret(secret_ref, new_token)
        updates["token_secret_ref"] = secret_ref

    updated = await store.update_repository(repo_id, updates) if updates else record
    return RepositoryResponse.from_record(updated or record)


@router.delete(
    "/{repo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_key)],
)
async def disconnect_repository(repo_id: str, store: StoreDep) -> Response:
    """Unlink a repository and delete its stored token."""
    record = await _require_repo(store, repo_id)
    if record.token_secret_ref:
        await get_secret_manager(get_settings()).delete_secret(record.token_secret_ref)
    await store.delete_repository(repo_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{repo_id}/test-connection",
    response_model=dict[str, object],
    dependencies=[Depends(require_api_key)],
)
async def test_connection(repo_id: str, store: StoreDep) -> dict[str, object]:
    """Check the stored token can still read the repository."""
    settings = get_settings()
    record = await _require_repo(store, repo_id)
    token = await get_secret_manager(settings).get_secret(record.token_secret_ref)
    if not token:
        return {"connected": False, "detail": "No access token is stored for this repository."}
    try:
        metadata = await GitHubClient(token, settings=settings).verify_access(
            record.owner, record.name
        )
    except GitHubError as exc:
        return {"connected": False, "detail": str(exc)}
    return {"connected": True, "repository": metadata["full_name"], "private": metadata["private"]}


@router.post(
    "/{repo_id}/poll",
    response_model=dict[str, object],
    dependencies=[Depends(require_api_key)],
)
async def poll_now(repo_id: str, store: StoreDep) -> dict[str, object]:
    """Poll this repository immediately instead of waiting for its interval."""
    from src.core.github_poller import GitHubRepoPoller

    settings = get_settings()
    record = await _require_repo(store, repo_id)
    poller = GitHubRepoPoller(
        store,
        get_telemetry_store(settings),
        get_secret_manager(settings),
        settings=settings,
    )
    outcome = await poller.poll_repository(record, now=datetime.now(UTC))
    return {
        "repo_id": outcome.repo_id,
        "commits_recorded": outcome.commits_recorded,
        "failed_runs_detected": outcome.runs_detected,
        "skipped_reason": outcome.skipped_reason,
        "error": outcome.error,
    }
