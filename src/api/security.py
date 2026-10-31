"""API authentication for mutating endpoints.

Authentication is opt-in: with no ``API_KEY`` configured OpsMind stays open so
local use needs no setup. Once a key is set, every mutating request must present
it. Reads, health probes, and the dashboard remain unauthenticated so the status
page keeps working without credentials.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException, status

from config.settings import Settings, get_settings

logger = logging.getLogger("opsmind.api.security")

API_KEY_HEADER = "X-API-Key"


def verify_api_key(provided: str | None, settings: Settings) -> None:
    """Raise ``HTTPException`` unless the request is authorised.

    Kept separate from the FastAPI dependency so the CLI and tests can reuse it.
    """
    if not settings.auth_required:
        return

    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing {API_KEY_HEADER} header.",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )

    # Constant-time comparison so a wrong key cannot be recovered by timing.
    if not hmac.compare_digest(provided, settings.api_key):
        logger.warning("rejected request with an invalid API key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency guarding mutating routes."""
    verify_api_key(x_api_key, get_settings())
