"""SSRF guard for user-supplied health-check URLs.

Validates scheme, pre-resolves DNS, and rejects loopback, RFC 1918, link-local,
and cloud-metadata addresses before any socket is opened.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class SSRFError(ValueError):
    """Raised when a URL would reach a prohibited address."""

    def __init__(self, message: str) -> None:
        if message.startswith("SSRF Protection Triggered"):
            text = message
        else:
            text = f"SSRF Protection Triggered: {message}"
        super().__init__(text)
        self.public_message = text


@dataclass(frozen=True)
class ValidatedTarget:
    """A URL whose hostname resolved to a public IP that is safe to pin."""

    url: str
    hostname: str
    port: int
    resolved_ip: str
    scheme: str


def _parse_literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if host.isdigit():
        try:
            return ipaddress.ip_address(int(host))
        except ValueError:
            return None
    return None


def _is_blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return True
    return any(address in network for network in _BLOCKED_NETWORKS)


class SSRFValidator:
    """Reject health URLs that resolve to non-public addresses."""

    def __init__(self, resolver=None) -> None:
        self._resolver = resolver or socket.getaddrinfo

    def validate_url(self, url: str) -> ValidatedTarget:
        """Return a pinned public target or raise ``SSRFError``."""
        if not url or not url.strip():
            raise SSRFError("health URL is empty")
        parsed = urlparse(url.strip())
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise SSRFError("only http and https URLs are allowed")
        if parsed.username or parsed.password:
            raise SSRFError("URLs with embedded credentials are not allowed")
        host = parsed.hostname
        if not host or any(char in host for char in ("\r", "\n", "\x00", " ")):
            raise SSRFError("health URL hostname is invalid")

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        literal = _parse_literal_ip(host)
        if literal is not None:
            if _is_blocked(literal):
                raise SSRFError(f"address {literal} is not a public health-check target")
            return ValidatedTarget(
                url=url.strip(),
                hostname=host,
                port=port,
                resolved_ip=str(literal),
                scheme=parsed.scheme,
            )

        try:
            infos = self._resolver(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise SSRFError(f"DNS resolution failed for {host}") from exc
        if not infos:
            raise SSRFError(f"DNS resolution returned no addresses for {host}")

        resolved: list[str] = []
        for info in infos:
            sockaddr = info[4]
            ip_text = sockaddr[0]
            address = ipaddress.ip_address(ip_text.split("%", 1)[0])
            if _is_blocked(address):
                raise SSRFError(f"{host} resolved to prohibited address {address}")
            resolved.append(str(address))

        return ValidatedTarget(
            url=url.strip(),
            hostname=host,
            port=port,
            resolved_ip=resolved[0],
            scheme=parsed.scheme,
        )
