"""GitHub repository monitoring: client, poller, and token handling.

All HTTP is served by an in-process transport, so these tests never reach the
network. The security-critical property is that a user's access token is stored
through SecretManager and never appears in a response or a log record.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from config.settings import Settings, get_settings
from src.core.github_client import (
    GitHubClient,
    GitHubError,
    GitHubRateLimited,
)
from src.core.github_poller import GitHubRepoPoller, ci_incident_dedup_id
from src.core.telemetry import SQLiteTelemetryStore, git_signal_id
from src.core.worker import LocalIncidentQueue
from src.infrastructure.interfaces import (
    RepositoryRecord,
    repository_id,
    repository_token_secret_ref,
)
from src.infrastructure.local.repository import SQLiteApplicationRepository
from src.infrastructure.local.secrets import LocalSecretManager
from src.main import app as fastapi_app

TOKEN = "ghp_secrettokenvalue"

COMMITS = [
    {
        "sha": "aaa111",
        "html_url": "https://github.com/acme/web/commit/aaa111",
        "commit": {
            "message": "Reduce connection pool size\n\nmore detail",
            "author": {"name": "Dev One", "date": "2026-10-30T10:00:00Z"},
        },
        "author": {"login": "devone"},
    },
    {
        "sha": "bbb222",
        "html_url": "https://github.com/acme/web/commit/bbb222",
        "commit": {
            "message": "Add caching layer",
            "author": {"name": "Dev Two", "date": "2026-10-30T09:00:00Z"},
        },
        "author": {"login": "devtwo"},
    },
]

FAILED_RUNS = {
    "workflow_runs": [
        {
            "id": 5002,
            "name": "CI",
            "status": "completed",
            "conclusion": "failure",
            "head_branch": "main",
            "head_sha": "aaa111",
            "actor": {"login": "devone"},
            "html_url": "https://github.com/acme/web/actions/runs/5002",
            "run_started_at": "2026-10-30T10:05:00Z",
        }
    ]
}

JOBS = {
    "jobs": [
        {"id": 91, "name": "build", "conclusion": "success"},
        {"id": 92, "name": "test", "conclusion": "failure"},
    ]
}

JOB_LOG = "\n".join(f"line {index}" for index in range(500)) + "\nE   AssertionError: expected 200"


def _settings(**overrides) -> Settings:
    base = {"github_log_tail_lines": 50, "github_rate_limit_floor": 10}
    base.update(overrides)
    return Settings(**base)


def _transport(*, etag: str = 'W/"abc"', remaining: str = "4999", calls: list | None = None):
    """An in-process GitHub API stand-in."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        headers = {"etag": etag, "x-ratelimit-remaining": remaining}

        if request.headers.get("If-None-Match") == etag:
            return httpx.Response(304, headers=headers)
        if path == "/repos/acme/web":
            return httpx.Response(
                200,
                json={
                    "full_name": "acme/web",
                    "default_branch": "main",
                    "private": True,
                    "description": "",
                },
                headers=headers,
            )
        if path == "/repos/acme/web/commits":
            return httpx.Response(200, json=COMMITS, headers=headers)
        if path == "/repos/acme/web/actions/runs":
            return httpx.Response(200, json=FAILED_RUNS, headers=headers)
        if path == "/repos/acme/web/actions/runs/5002/jobs":
            return httpx.Response(200, json=JOBS, headers=headers)
        if path == "/repos/acme/web/actions/jobs/92/logs":
            return httpx.Response(200, text=JOB_LOG, headers=headers)
        return httpx.Response(404, json={"message": "Not Found"}, headers=headers)

    return httpx.MockTransport(handler)


def _client(**kwargs) -> GitHubClient:
    return GitHubClient(TOKEN, settings=_settings(), transport=_transport(**kwargs))


# --- client -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_access_returns_repository_metadata():
    metadata = await _client().verify_access("acme", "web")
    assert metadata["full_name"] == "acme/web"
    assert metadata["default_branch"] == "main"
    assert metadata["private"] is True


@pytest.mark.asyncio
async def test_list_commits_parses_author_and_first_line_only():
    result = await _client().list_commits("acme", "web", branch="main")
    assert [c.sha for c in result.items] == ["aaa111", "bbb222"]
    assert result.items[0].author == "devone"
    assert result.items[0].message == "Reduce connection pool size"
    assert result.rate_limit_remaining == 4999


@pytest.mark.asyncio
async def test_matching_etag_returns_not_modified_without_items():
    """A 304 costs no API quota, which is the point of sending the ETag."""
    result = await _client().list_commits("acme", "web", etag='W/"abc"')
    assert result.not_modified is True
    assert result.items == []


@pytest.mark.asyncio
async def test_failed_runs_are_parsed():
    result = await _client().list_failed_runs("acme", "web")
    assert len(result.items) == 1
    run = result.items[0]
    assert run.run_id == 5002
    assert run.conclusion == "failure"
    assert run.commit_sha == "aaa111"


@pytest.mark.asyncio
async def test_failed_job_log_is_tailed_to_the_configured_limit():
    job_name, log = await _client().get_failed_job_log("acme", "web", 5002)
    assert job_name == "test"
    lines = log.splitlines()
    assert len(lines) == 50
    # The useful error is at the end, which is why the tail is kept.
    assert "AssertionError" in lines[-1]


@pytest.mark.asyncio
async def test_exhausted_rate_limit_raises_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={}, headers={"x-ratelimit-remaining": "0"})

    client = GitHubClient(TOKEN, settings=_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubRateLimited):
        await client.list_commits("acme", "web")


@pytest.mark.asyncio
async def test_bad_token_raises_a_clear_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = GitHubClient(TOKEN, settings=_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubError, match="401"):
        await client.verify_access("acme", "web")


def test_api_base_url_is_ssrf_validated():
    """The base URL is configuration, so it gets the same guard as a health URL."""
    from src.core.security import SSRFError

    with pytest.raises(SSRFError):
        GitHubClient(TOKEN, settings=_settings(github_api_base_url="http://169.254.169.254"))


# --- secret storage ---------------------------------------------------------


@pytest.mark.asyncio
async def test_local_secret_manager_stores_and_deletes(tmp_path):
    manager = LocalSecretManager(settings=_settings(), path=tmp_path / "secrets.json")
    assert await manager.get_secret("MISSING") is None

    await manager.put_secret("gh-token", TOKEN)
    assert await manager.get_secret("gh-token") == TOKEN
    # Owner-only permissions: these are credentials on a developer machine.
    assert oct((tmp_path / "secrets.json").stat().st_mode)[-3:] == "600"

    assert await manager.delete_secret("gh-token") is True
    assert await manager.get_secret("gh-token") is None
    assert await manager.delete_secret("gh-token") is False


@pytest.mark.asyncio
async def test_environment_takes_precedence_over_the_secrets_file(tmp_path, monkeypatch):
    manager = LocalSecretManager(settings=_settings(), path=tmp_path / "secrets.json")
    await manager.put_secret("SHARED", "from-file")
    monkeypatch.setenv("SHARED", "from-env")
    assert await manager.get_secret("SHARED") == "from-env"


# --- poller -----------------------------------------------------------------


@pytest.fixture
def poller_env(tmp_path):
    db = tmp_path / "github.db"
    store = SQLiteApplicationRepository(db_path=db)
    telemetry = SQLiteTelemetryStore(db)
    secrets = LocalSecretManager(settings=_settings(), path=tmp_path / "secrets.json")
    queue = LocalIncidentQueue()
    return store, telemetry, secrets, queue


async def _link(store, secrets, **overrides) -> RepositoryRecord:
    repo_id = repository_id("acme", "web")
    secret_ref = repository_token_secret_ref(repo_id)
    await secrets.put_secret(secret_ref, TOKEN)
    record = RepositoryRecord(
        repo_id=repo_id,
        app_id="checkout-api",
        owner="acme",
        name="web",
        token_secret_ref=secret_ref,
        **overrides,
    )
    await store.save_repository(record)
    return record


def _poller(env, **kwargs):
    store, telemetry, secrets, queue = env
    return GitHubRepoPoller(
        store,
        telemetry,
        secrets,
        queue=queue,
        settings=_settings(),
        client_factory=lambda token: GitHubClient(
            token, settings=_settings(), transport=_transport(**kwargs)
        ),
    )


@pytest.mark.asyncio
async def test_poll_records_commits_as_git_telemetry(poller_env):
    store, telemetry, secrets, _ = poller_env
    record = await _link(store, secrets)

    outcome = await _poller(poller_env).poll_repository(record)
    assert outcome.commits_recorded == 2

    signals = await telemetry.list_signals(
        "checkout-api", since=datetime.now(UTC) - timedelta(days=365)
    )
    shas = {s.metadata.get("commit_sha") for s in signals if s.source == "git"}
    assert shas == {"aaa111", "bbb222"}


@pytest.mark.asyncio
async def test_commit_cursor_prevents_reprocessing(poller_env):
    store, _, secrets, _ = poller_env
    record = await _link(store, secrets)
    poller = _poller(poller_env)

    first = await poller.poll_repository(record)
    assert first.commits_recorded == 2

    stored = await store.get_repository(record.repo_id)
    assert stored.last_commit_sha == "aaa111"

    # Same API response, but the cursor now stops at the newest known commit.
    second = await poller.poll_repository(stored)
    assert second.commits_recorded == 0


@pytest.mark.asyncio
async def test_failed_run_is_enqueued_once(poller_env):
    store, _, secrets, queue = poller_env
    record = await _link(store, secrets)
    poller = _poller(poller_env)

    outcome = await poller.poll_repository(record)
    assert outcome.runs_detected == 1

    message = await queue.dequeue(timeout=0.1)
    assert message is not None
    assert message.event_type == "github_actions"
    assert message.deduplication_id == ci_incident_dedup_id(record.repo_id, 5002)
    assert any("AssertionError" in line for line in message.payload["logs"])

    stored = await store.get_repository(record.repo_id)
    assert stored.last_workflow_run_id == 5002

    # A second poll must not re-enqueue the same run.
    assert (await poller.poll_repository(stored)).runs_detected == 0


@pytest.mark.asyncio
async def test_poller_and_webhook_agree_on_the_ci_dedup_id(poller_env):
    """Both ingestion paths must produce the same identity for one run."""
    store, _, secrets, _ = poller_env
    record = await _link(store, secrets)
    webhook_style = f"ghrun-{record.owner}__{record.name}-5002".lower()
    assert ci_incident_dedup_id(record.repo_id, 5002) == webhook_style


@pytest.mark.asyncio
async def test_poller_and_webhook_agree_on_the_commit_signal_id(poller_env):
    store, telemetry, secrets, _ = poller_env
    record = await _link(store, secrets)
    await _poller(poller_env).poll_repository(record)

    signals = await telemetry.list_signals(
        "checkout-api", since=datetime.now(UTC) - timedelta(days=365)
    )
    ids = {s.signal_id for s in signals if s.source == "git"}
    assert git_signal_id("acme", "web", "aaa111") in ids


@pytest.mark.asyncio
async def test_repository_without_a_token_is_skipped(poller_env):
    store, _, _, _ = poller_env
    record = RepositoryRecord(
        repo_id="acme__notoken",
        app_id="checkout-api",
        owner="acme",
        name="web",
        token_secret_ref="opsmind/github/missing",
    )
    await store.save_repository(record)

    outcome = await _poller(poller_env).poll_repository(record)
    assert outcome.skipped_reason == "no access token stored"
    assert outcome.commits_recorded == 0


@pytest.mark.asyncio
async def test_repository_below_the_rate_limit_floor_is_skipped(poller_env):
    store, _, secrets, _ = poller_env
    record = await _link(store, secrets)
    await store.update_repository(record.repo_id, {"rate_limit_remaining": 1})
    stored = await store.get_repository(record.repo_id)

    outcome = await _poller(poller_env).poll_repository(stored)
    assert outcome.skipped_reason == "below configured rate limit floor"


@pytest.mark.asyncio
async def test_disabled_features_are_not_polled(poller_env):
    store, _, secrets, queue = poller_env
    record = await _link(store, secrets, commits_enabled=False, actions_enabled=False)

    outcome = await _poller(poller_env).poll_repository(record)
    assert outcome.commits_recorded == 0
    assert outcome.runs_detected == 0
    assert await queue.dequeue(timeout=0.05) is None


@pytest.mark.asyncio
async def test_run_once_respects_the_poll_interval(poller_env):
    store, _, secrets, _ = poller_env
    record = await _link(store, secrets, poll_interval_seconds=3600)
    await store.update_repository(record.repo_id, {"last_polled_at": datetime.now(UTC)})

    assert await _poller(poller_env).run_once() == []


@pytest.mark.asyncio
async def test_api_errors_are_recorded_without_crashing_the_cycle(poller_env):
    store, telemetry, secrets, queue = poller_env
    record = await _link(store, secrets)

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "server error"})

    poller = GitHubRepoPoller(
        store,
        telemetry,
        secrets,
        queue=queue,
        settings=_settings(),
        client_factory=lambda token: GitHubClient(
            token, settings=_settings(), transport=httpx.MockTransport(failing)
        ),
    )
    outcome = await poller.poll_repository(record)
    assert outcome.error is not None
    stored = await store.get_repository(record.repo_id)
    assert stored.last_error is not None


@pytest.mark.asyncio
async def test_token_never_appears_in_logs(poller_env, caplog):
    """A leaked token in a log file is as bad as one in a response body."""
    store, _, secrets, _ = poller_env
    record = await _link(store, secrets)

    with caplog.at_level(logging.DEBUG):
        await _poller(poller_env).poll_repository(record)

    assert TOKEN not in caplog.text


# --- repository link persistence and API ------------------------------------


@pytest.mark.asyncio
async def test_repository_link_round_trips(poller_env):
    store, _, secrets, _ = poller_env
    record = await _link(store, secrets)

    stored = await store.get_repository(record.repo_id)
    assert stored is not None
    assert stored.full_name == "acme/web"
    assert len(await store.list_repositories(app_id="checkout-api")) == 1

    await store.update_repository(record.repo_id, {"commits_enabled": False})
    assert (await store.get_repository(record.repo_id)).commits_enabled is False

    assert await store.delete_repository(record.repo_id) is True
    assert await store.get_repository(record.repo_id) is None


def test_repository_id_is_deterministic_and_case_insensitive():
    assert repository_id("Acme", "Web") == repository_id("acme", "web")


def test_connect_endpoint_never_returns_the_token(monkeypatch, tmp_path):
    """The response model has no token field, and must not grow one."""
    import src.api.routes_repositories as routes

    monkeypatch.setattr(
        routes,
        "GitHubClient",
        lambda token, settings=None: type(
            "Stub",
            (),
            {
                "verify_access": staticmethod(
                    lambda owner, name: _async_value(
                        {
                            "full_name": f"{owner}/{name}",
                            "default_branch": "main",
                            "private": False,
                            "description": "",
                        }
                    )
                )
            },
        )(),
    )
    monkeypatch.setenv("LOCAL_SECRETS_PATH", str(tmp_path / "secrets.json"))
    get_settings.cache_clear()
    try:
        with TestClient(fastapi_app) as client:
            client.post(
                "/api/v1/applications",
                json={
                    "app_id": "repo-api-app",
                    "name": "Repo API App",
                    "health_url": "https://example.com/healthz",
                },
            )
            created = client.post(
                "/api/v1/repositories",
                json={
                    "app_id": "repo-api-app",
                    "owner": "acme",
                    "name": "web",
                    "access_token": TOKEN,
                },
            )
            assert created.status_code == 201
            body = created.json()
            assert body["token_configured"] is True
            assert TOKEN not in json.dumps(body)
            assert "access_token" not in body
            assert "token_secret_ref" not in body

            listed = client.get("/api/v1/repositories").json()
            assert TOKEN not in json.dumps(listed)

            client.delete(f"/api/v1/repositories/{body['repo_id']}")
            client.delete("/api/v1/applications/repo-api-app")
    finally:
        get_settings.cache_clear()


def _async_value(value):
    async def _coro():
        return value

    return _coro()


def test_unknown_repository_link_is_404():
    with TestClient(fastapi_app) as client:
        assert client.get("/api/v1/repositories/nope__nope").status_code == 404


def test_successful_workflow_run_webhook_is_ignored(monkeypatch):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(fastapi_app) as client:
            resp = client.post(
                "/api/v1/webhooks/github",
                json={
                    "repository": {"name": "web", "owner": {"login": "acme"}},
                    "workflow_run": {"id": 1, "conclusion": "success", "name": "CI"},
                },
                headers={"X-GitHub-Event": "workflow_run"},
            )
        assert resp.status_code == 202
        assert resp.json()["status"] == "ignored"
    finally:
        get_settings.cache_clear()


def test_failed_workflow_run_webhook_is_queued(monkeypatch):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(fastapi_app) as client:
            resp = client.post(
                "/api/v1/webhooks/github",
                json={
                    "repository": {"name": "web", "owner": {"login": "acme"}},
                    "workflow_run": {
                        "id": 777,
                        "conclusion": "failure",
                        "name": "CI",
                        "head_branch": "main",
                        "head_sha": "aaa111",
                        "actor": {"login": "devone"},
                        "html_url": "https://github.com/acme/web/actions/runs/777",
                    },
                },
                headers={"X-GitHub-Event": "workflow_run"},
            )
        assert resp.status_code == 202
        assert resp.json()["status"] == "queued"
        assert resp.json()["environment"] == "ci"
    finally:
        get_settings.cache_clear()
