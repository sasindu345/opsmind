"""Background polling of linked GitHub repositories.

Polling rather than webhooks is the primary path because it needs no public URL,
so a user can connect a repository from a laptop. The webhook receiver is kept
for real-time setups; both write the same deterministic telemetry signal id, so
a commit arriving twice is stored once.

Structured like ``SyntheticHealthWorker`` so the two background workers start,
stop, and are tested the same way.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from config.settings import Settings, get_settings
from src.core.github_client import CommitInfo, GitHubClient, GitHubError, GitHubRateLimited
from src.core.telemetry import TelemetrySignal, git_signal_id
from src.core.worker import IncidentMessage
from src.infrastructure.interfaces import RepositoryRecord

logger = logging.getLogger("opsmind.github.poller")


@dataclass
class PollOutcome:
    """What one repository poll did."""

    repo_id: str
    commits_recorded: int = 0
    runs_detected: int = 0
    skipped_reason: str | None = None
    error: str | None = None


def ci_incident_dedup_id(repo_id: str, run_id: int) -> str:
    """Stable identity for a failed CI run, so it is triaged once."""
    return f"ghrun-{repo_id}-{run_id}"


class GitHubRepoPoller:
    """Polls linked repositories for new commits and failed CI runs."""

    def __init__(
        self,
        repo_store,
        telemetry_store,
        secret_manager,
        *,
        queue=None,
        settings: Settings | None = None,
        client_factory=None,
    ) -> None:
        self.settings = settings or get_settings()
        self._repo_store = repo_store
        self._telemetry_store = telemetry_store
        self._secret_manager = secret_manager
        self._queue = queue
        self._client_factory = client_factory or self._default_client_factory
        self._stop = asyncio.Event()

    def _default_client_factory(self, token: str) -> GitHubClient:
        return GitHubClient(token, settings=self.settings)

    def _get_queue(self):
        if self._queue is None:
            from src.core.worker import get_local_queue

            self._queue = get_local_queue()
        return self._queue

    def _is_due(self, repo: RepositoryRecord, moment: datetime) -> bool:
        if repo.last_polled_at is None:
            return True
        last = repo.last_polled_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        interval = repo.poll_interval_seconds or self.settings.github_poll_interval_seconds
        return (moment - last).total_seconds() >= interval

    async def run_once(self, now: datetime | None = None) -> list[PollOutcome]:
        """Poll every repository whose interval has elapsed."""
        moment = now or datetime.now(UTC)
        repos = await self._repo_store.list_repositories()
        outcomes: list[PollOutcome] = []

        for repo in repos[: self.settings.github_max_repos_per_cycle]:
            if not self._is_due(repo, moment):
                continue
            try:
                outcomes.append(await self.poll_repository(repo, now=moment))
            except Exception as exc:
                logger.exception("polling %s failed", repo.full_name)
                outcomes.append(PollOutcome(repo_id=repo.repo_id, error=str(exc)))
                await self._repo_store.update_repository(
                    repo.repo_id,
                    {"last_polled_at": moment, "last_error": str(exc)[:500]},
                )
        return outcomes

    async def poll_repository(
        self,
        repo: RepositoryRecord,
        *,
        now: datetime | None = None,
    ) -> PollOutcome:
        """Poll one repository, advancing its cursors."""
        moment = now or datetime.now(UTC)
        outcome = PollOutcome(repo_id=repo.repo_id)

        token = await self._secret_manager.get_secret(repo.token_secret_ref)
        if not token:
            outcome.skipped_reason = "no access token stored"
            await self._repo_store.update_repository(
                repo.repo_id,
                {"last_polled_at": moment, "last_error": outcome.skipped_reason},
            )
            return outcome

        if (
            repo.rate_limit_remaining is not None
            and repo.rate_limit_remaining < self.settings.github_rate_limit_floor
        ):
            outcome.skipped_reason = "below configured rate limit floor"
            logger.info("skipping %s: %s", repo.full_name, outcome.skipped_reason)
            return outcome

        client = self._client_factory(token)
        updates: dict[str, object] = {"last_polled_at": moment, "last_error": None}

        try:
            if repo.commits_enabled:
                outcome.commits_recorded = await self._sync_commits(repo, client, updates, moment)
            if repo.actions_enabled:
                outcome.runs_detected = await self._sync_failed_runs(repo, client, updates)
        except GitHubRateLimited as exc:
            outcome.error = str(exc)
            updates["last_error"] = str(exc)
            updates["rate_limit_remaining"] = 0
        except GitHubError as exc:
            outcome.error = str(exc)
            updates["last_error"] = str(exc)

        await self._repo_store.update_repository(repo.repo_id, updates)
        return outcome

    async def _sync_commits(
        self,
        repo: RepositoryRecord,
        client: GitHubClient,
        updates: dict[str, object],
        moment: datetime,
    ) -> int:
        since = moment - timedelta(hours=self.settings.github_commit_lookback_hours)
        result = await client.list_commits(
            repo.owner,
            repo.name,
            branch=repo.default_branch,
            since=since,
            etag=repo.commits_etag,
        )
        if result.rate_limit_remaining is not None:
            updates["rate_limit_remaining"] = result.rate_limit_remaining
        if result.not_modified:
            return 0
        updates["commits_etag"] = result.etag

        commits: list[CommitInfo] = result.items
        if not commits:
            return 0

        # Stop at the last commit already seen; the API returns newest first.
        fresh: list[CommitInfo] = []
        for commit in commits:
            if repo.last_commit_sha and commit.sha == repo.last_commit_sha:
                break
            fresh.append(commit)

        for commit in reversed(fresh):
            await self._telemetry_store.save_signal(
                TelemetrySignal(
                    # Deterministic, so the webhook path cannot duplicate it.
                    signal_id=git_signal_id(repo.owner, repo.name, commit.sha),
                    source="git",
                    app_id=repo.app_id,
                    service=repo.app_id,
                    environment="production",
                    timestamp=commit.committed_at,
                    level="INFO",
                    raw_message=commit.message,
                    metadata={
                        "commit_sha": commit.sha,
                        "author": commit.author,
                        "repository": repo.full_name,
                        "url": commit.url,
                    },
                )
            )

        if commits:
            updates["last_commit_sha"] = commits[0].sha
        if fresh:
            logger.info("recorded %d new commits for %s", len(fresh), repo.full_name)
        return len(fresh)

    async def _sync_failed_runs(
        self,
        repo: RepositoryRecord,
        client: GitHubClient,
        updates: dict[str, object],
    ) -> int:
        result = await client.list_failed_runs(repo.owner, repo.name, etag=repo.runs_etag)
        if result.rate_limit_remaining is not None:
            updates["rate_limit_remaining"] = result.rate_limit_remaining
        if result.not_modified:
            return 0
        updates["runs_etag"] = result.etag

        runs = result.items
        if not runs:
            return 0

        cursor = repo.last_workflow_run_id or 0
        fresh = [run for run in runs if run.run_id > cursor]
        highest = max((run.run_id for run in runs), default=cursor)
        if highest > cursor:
            updates["last_workflow_run_id"] = highest

        for run in sorted(fresh, key=lambda r: r.run_id):
            await self._enqueue_ci_failure(repo, client, run)

        if fresh:
            logger.warning("detected %d failed CI runs for %s", len(fresh), repo.full_name)
        return len(fresh)

    async def _enqueue_ci_failure(self, repo: RepositoryRecord, client: GitHubClient, run) -> None:
        """Turn a failed workflow run into queued triage work.

        Enqueued rather than analysed inline so the existing worker supplies
        Drain3 clustering, correlation, the LLM call, the heuristic fallback,
        and idempotency, with no parallel analysis path.
        """
        job_name, log_tail = await client.get_failed_job_log(repo.owner, repo.name, run.run_id)
        log_lines = [
            f"GitHub Actions workflow '{run.name}' failed on branch {run.branch}.",
            f"Failed job: {job_name or 'unknown'} (run {run.run_id}, actor {run.actor}).",
            f"Commit: {run.commit_sha[:7]} - {run.html_url}",
        ]
        if log_tail:
            log_lines.extend(log_tail.splitlines())

        message = IncidentMessage(
            message_id=uuid.uuid4().hex,
            correlation_id=uuid.uuid4().hex,
            service=repo.app_id,
            environment="ci",
            event_type="github_actions",
            payload={
                "logs": log_lines,
                "context": (
                    f"GitHub Actions workflow '{run.name}' failed for {repo.full_name}. "
                    "Diagnose the build or test failure and recommend a specific fix."
                ),
                "generate_report": False,
                "workflow_run_id": run.run_id,
                "workflow_name": run.name,
                "repository": repo.full_name,
                "run_url": run.html_url,
                "deployments": [
                    {
                        "commit_sha": run.commit_sha,
                        "author": run.actor,
                        "service": repo.app_id,
                        "environment": "ci",
                        "message": f"CI run for {run.name}",
                    }
                ]
                if run.commit_sha
                else [],
            },
            deduplication_id=ci_incident_dedup_id(repo.repo_id, run.run_id),
        )
        await self._get_queue().enqueue(message)

    async def run(self) -> None:
        """Poll until ``stop`` is called."""
        logger.info("github repository poller started")
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("github poller cycle failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.settings.github_poll_interval_seconds,
                )
            except TimeoutError:
                continue
        logger.info("github repository poller stopped")

    def stop(self) -> None:
        self._stop.set()
