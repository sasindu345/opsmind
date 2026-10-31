"""Minimal async GitHub REST client for commit and CI-run monitoring.

Only the handful of endpoints OpsMind needs, with conditional requests so an
unchanged poll costs no API quota, and rate-limit awareness so a busy account is
never exhausted by polling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from config.settings import Settings, get_settings
from src.core.security import SSRFError, SSRFValidator

logger = logging.getLogger("opsmind.github")

# 304 means the resource is unchanged since the stored ETag, and costs no quota.
NOT_MODIFIED = 304


class GitHubError(RuntimeError):
    """A GitHub API call failed in a way the caller should surface."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubRateLimited(GitHubError):
    """The token has no remaining API quota."""


@dataclass
class CommitInfo:
    """One commit, reduced to what correlation needs."""

    sha: str
    author: str
    message: str
    committed_at: datetime
    url: str = ""
    changed_files: list[str] = field(default_factory=list)


@dataclass
class WorkflowRunInfo:
    """One GitHub Actions run."""

    run_id: int
    name: str
    status: str
    conclusion: str
    branch: str
    commit_sha: str
    actor: str
    html_url: str
    started_at: datetime | None = None


@dataclass
class PagedResult:
    """A conditional-request response: ``not_modified`` means nothing changed."""

    items: list[Any]
    etag: str | None = None
    not_modified: bool = False
    rate_limit_remaining: int | None = None


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("could not parse GitHub timestamp %r", raw)
        return None


class GitHubClient:
    """Async GitHub REST client scoped to one access token."""

    def __init__(
        self,
        token: str,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._token = token
        self._transport = transport
        self.base_url = self.settings.github_api_base_url.rstrip("/")

        # A configurable base URL is user input, so it is validated like any
        # other. This stops a GitHub Enterprise host being pointed at a cloud
        # metadata address.
        try:
            SSRFValidator().validate_url(self.base_url)
        except SSRFError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise GitHubError(f"Invalid GitHub API base URL: {exc}") from exc

    def _headers(self, etag: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "OpsMind/1.0",
            "Authorization": f"Bearer {self._token}",
        }
        if etag:
            headers["If-None-Match"] = etag
        return headers

    async def _request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        etag: str | None = None,
        expect_text: bool = False,
    ) -> tuple[int, Any, dict[str, str]]:
        url = f"{self.base_url}{path}"
        timeout = self.settings.github_request_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            try:
                response = await client.get(url, params=params, headers=self._headers(etag))
            except httpx.HTTPError as exc:
                raise GitHubError(f"GitHub request failed: {exc}") from exc

        remaining = response.headers.get("x-ratelimit-remaining")
        if response.status_code == 403 and remaining == "0":
            raise GitHubRateLimited("GitHub API rate limit exhausted", status_code=403)
        if response.status_code == 401:
            raise GitHubError("GitHub rejected the token (401)", status_code=401)
        if response.status_code == 404:
            raise GitHubError("Repository or resource not found (404)", status_code=404)
        if response.status_code == NOT_MODIFIED:
            return response.status_code, None, dict(response.headers)
        if response.status_code >= 400:
            raise GitHubError(
                f"GitHub returned {response.status_code}",
                status_code=response.status_code,
            )

        payload = response.text if expect_text else response.json()
        return response.status_code, payload, dict(response.headers)

    @staticmethod
    def _remaining(headers: dict[str, str]) -> int | None:
        raw = headers.get("x-ratelimit-remaining")
        try:
            return int(raw) if raw is not None else None
        except ValueError:
            return None

    async def verify_access(self, owner: str, name: str) -> dict[str, Any]:
        """Confirm the token can read the repository, returning its metadata."""
        _, payload, _ = await self._request(f"/repos/{owner}/{name}")
        return {
            "full_name": payload.get("full_name", f"{owner}/{name}"),
            "default_branch": payload.get("default_branch", "main"),
            "private": payload.get("private", False),
            "description": payload.get("description") or "",
        }

    async def list_commits(
        self,
        owner: str,
        name: str,
        *,
        branch: str | None = None,
        since: datetime | None = None,
        etag: str | None = None,
        per_page: int = 30,
    ) -> PagedResult:
        """List recent commits, newest first."""
        params: dict[str, Any] = {"per_page": per_page}
        if branch:
            params["sha"] = branch
        if since:
            params["since"] = since.isoformat()

        status_code, payload, headers = await self._request(
            f"/repos/{owner}/{name}/commits", params=params, etag=etag
        )
        remaining = self._remaining(headers)
        if status_code == NOT_MODIFIED:
            return PagedResult(
                items=[], etag=etag, not_modified=True, rate_limit_remaining=remaining
            )

        commits: list[CommitInfo] = []
        for entry in payload or []:
            commit = entry.get("commit", {})
            author = commit.get("author", {}) or {}
            commits.append(
                CommitInfo(
                    sha=entry.get("sha", ""),
                    author=(entry.get("author") or {}).get("login")
                    or author.get("name", "unknown"),
                    message=commit.get("message", "").splitlines()[0]
                    if commit.get("message")
                    else "",
                    committed_at=_parse_timestamp(author.get("date"))
                    or datetime.now().astimezone(),
                    url=entry.get("html_url", ""),
                )
            )
        return PagedResult(
            items=commits,
            etag=headers.get("etag"),
            rate_limit_remaining=remaining,
        )

    async def list_failed_runs(
        self,
        owner: str,
        name: str,
        *,
        etag: str | None = None,
        per_page: int = 20,
    ) -> PagedResult:
        """List workflow runs that concluded in failure, newest first."""
        params: dict[str, Any] = {"status": "failure", "per_page": per_page}
        status_code, payload, headers = await self._request(
            f"/repos/{owner}/{name}/actions/runs", params=params, etag=etag
        )
        remaining = self._remaining(headers)
        if status_code == NOT_MODIFIED:
            return PagedResult(
                items=[], etag=etag, not_modified=True, rate_limit_remaining=remaining
            )

        runs: list[WorkflowRunInfo] = []
        for entry in (payload or {}).get("workflow_runs", []):
            runs.append(
                WorkflowRunInfo(
                    run_id=int(entry.get("id", 0)),
                    name=entry.get("name") or "workflow",
                    status=entry.get("status", ""),
                    conclusion=entry.get("conclusion", ""),
                    branch=entry.get("head_branch") or "",
                    commit_sha=entry.get("head_sha") or "",
                    actor=(entry.get("actor") or {}).get("login", "unknown"),
                    html_url=entry.get("html_url", ""),
                    started_at=_parse_timestamp(entry.get("run_started_at")),
                )
            )
        return PagedResult(
            items=runs,
            etag=headers.get("etag"),
            rate_limit_remaining=remaining,
        )

    async def get_failed_job_log(self, owner: str, name: str, run_id: int) -> tuple[str, str]:
        """Return the failed job's name and the tail of its log.

        Only the tail is kept: the useful error is at the end, and a full CI log
        would blow past the LLM's context for no benefit.
        """
        _, payload, _ = await self._request(f"/repos/{owner}/{name}/actions/runs/{run_id}/jobs")
        jobs = (payload or {}).get("jobs", [])
        failed = next(
            (job for job in jobs if job.get("conclusion") not in (None, "success", "skipped")),
            None,
        )
        if failed is None:
            return "", ""

        job_name = failed.get("name", "job")
        job_id = failed.get("id")
        if job_id is None:
            return job_name, ""

        try:
            _, text, _ = await self._request(
                f"/repos/{owner}/{name}/actions/jobs/{job_id}/logs",
                expect_text=True,
            )
        except GitHubError as exc:
            # Logs expire, so a missing log must not abort the whole poll.
            logger.info("could not fetch logs for job %s: %s", job_id, exc)
            return job_name, ""

        lines = (text or "").splitlines()
        tail = lines[-self.settings.github_log_tail_lines :]
        return job_name, "\n".join(tail)
