"""API key authentication on mutating endpoints.

OpsMind previously had no authentication at all: every mounted route was fully
open. Authentication is opt-in so local use needs no setup, which these tests
pin down in both directions.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from config.settings import Settings, get_settings
from src.api.security import verify_api_key
from src.main import app


def test_no_key_configured_allows_the_request():
    """The zero-setup local default must stay open."""
    verify_api_key(None, Settings(api_key=""))


def test_missing_header_is_rejected_when_a_key_is_configured():
    with pytest.raises(HTTPException) as exc:
        verify_api_key(None, Settings(api_key="secret"))
    assert exc.value.status_code == 401
    assert "X-API-Key" in exc.value.detail


def test_wrong_key_is_rejected():
    with pytest.raises(HTTPException) as exc:
        verify_api_key("wrong", Settings(api_key="secret"))
    assert exc.value.status_code == 401
    assert "Invalid" in exc.value.detail


def test_correct_key_is_accepted():
    verify_api_key("secret", Settings(api_key="secret"))


def test_key_comparison_is_not_a_prefix_match():
    for candidate in ("sec", "secretsecret", "Secret"):
        with pytest.raises(HTTPException):
            verify_api_key(candidate, Settings(api_key="secret"))


def test_mutating_route_requires_the_key_but_reads_stay_open(monkeypatch):
    monkeypatch.setenv("API_KEY", "integration-key")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            payload = {
                "app_id": "auth-probe-app",
                "name": "Auth Probe App",
                "health_url": "https://example.com/healthz",
            }

            unauthenticated = client.post("/api/v1/applications", json=payload)
            assert unauthenticated.status_code == 401

            # Reads must not require credentials, so the dashboard still renders.
            assert client.get("/api/v1/applications").status_code == 200
            assert client.get("/healthz").status_code == 200
            assert client.get("/readyz").status_code == 200

            authenticated = client.post(
                "/api/v1/applications",
                json=payload,
                headers={"X-API-Key": "integration-key"},
            )
            assert authenticated.status_code in (201, 409)
            client.delete(
                "/api/v1/applications/auth-probe-app",
                headers={"X-API-Key": "integration-key"},
            )
    finally:
        get_settings.cache_clear()


def test_session_endpoint_reports_auth_requirement(monkeypatch):
    """The dashboard needs this before it can know to prompt for a key."""
    monkeypatch.delenv("API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            body = client.get("/api/v1/session").json()
        assert body["auth_required"] is False
        assert "deployment_mode" in body
        assert "remediation_execution_enabled" in body
    finally:
        get_settings.cache_clear()


def test_webhooks_stay_exempt_from_api_key_auth(monkeypatch):
    """GitHub cannot send a custom header; webhooks are guarded by HMAC instead."""
    monkeypatch.setenv("API_KEY", "integration-key")
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/webhooks/github",
                json={"repository": {"name": "opsmind"}, "after": "abc123"},
                headers={"X-GitHub-Event": "push"},
            )
        assert resp.status_code != 401
    finally:
        get_settings.cache_clear()
