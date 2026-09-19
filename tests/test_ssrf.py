import socket

import pytest

from src.core.security import SSRFError, SSRFValidator, ValidatedTarget


def _resolver_returning(ip: str):
    def resolve(host, port, family, socktype):
        return [(family, socktype, 0, "", (ip, port))]

    return resolve


def test_literal_metadata_ip_is_rejected():
    validator = SSRFValidator()
    with pytest.raises(SSRFError, match="SSRF Protection Triggered"):
        validator.validate_url("http://169.254.169.254/latest/meta-data")


def test_literal_loopback_and_private_ranges_are_rejected():
    validator = SSRFValidator()
    for url in (
        "http://127.0.0.1:8000/healthz",
        "http://10.0.0.8/health",
        "http://192.168.1.20/health",
        "http://172.16.4.2/health",
        "http://[::1]/health",
    ):
        with pytest.raises(SSRFError, match="SSRF Protection Triggered"):
            validator.validate_url(url)


def test_localhost_dns_is_rejected():
    validator = SSRFValidator()
    with pytest.raises(SSRFError, match="SSRF Protection Triggered"):
        validator.validate_url("http://localhost:8000/healthz")


def test_resolved_private_address_is_rejected():
    validator = SSRFValidator(resolver=_resolver_returning("10.1.2.3"))
    with pytest.raises(SSRFError, match="prohibited address"):
        validator.validate_url("http://health.internal/healthz")


def test_public_address_is_pinned():
    validator = SSRFValidator(resolver=_resolver_returning("1.1.1.1"))
    target = validator.validate_url("https://api.example.com/healthz")
    assert target == ValidatedTarget(
        url="https://api.example.com/healthz",
        hostname="api.example.com",
        port=443,
        resolved_ip="1.1.1.1",
        scheme="https",
    )


def test_non_http_scheme_is_rejected():
    validator = SSRFValidator()
    with pytest.raises(SSRFError, match="only http and https"):
        validator.validate_url("file:///etc/passwd")


def test_dns_failure_is_rejected(monkeypatch):
    def fail(host, port, family, socktype):
        raise socket.gaierror("no such host")

    validator = SSRFValidator(resolver=fail)
    with pytest.raises(SSRFError, match="DNS resolution failed"):
        validator.validate_url("http://does-not-resolve.example/health")
