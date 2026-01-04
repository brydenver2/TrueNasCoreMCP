"""Authentication helpers for the HTTP MCP server."""

from __future__ import annotations

import hmac
import logging
from typing import Set

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param

from .settings import http_settings

logger = logging.getLogger(__name__)


class HTTPBearerOrHeader(HTTPBearer):
    """Accept Bearer tokens via Authorization or X-Access-Token headers."""

    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials:  # type: ignore[override]
        # Prefer "Authorization" header; fall back to custom header if needed.
        auth_headers: list[str] = []
        for name, value in request.scope.get("headers", []):
            if name.lower() == b"authorization" and value is not None:
                try:
                    auth_headers.append(value.decode("latin-1"))
                except UnicodeDecodeError:
                    continue

        if not auth_headers:
            header_accessor = getattr(request.headers, "getlist", None)
            if callable(header_accessor):
                auth_headers = header_accessor("Authorization")
            else:
                single_header = request.headers.get("Authorization")
                if single_header:
                    auth_headers = [single_header]

        for header_value in auth_headers:
            # Split on commas to support multiple values in a single header
            for candidate in (segment.strip() for segment in header_value.split(",")):
                if not candidate:
                    continue
                scheme, credentials = get_authorization_scheme_param(candidate)
                if scheme and scheme.lower() == "bearer" and credentials:
                    return HTTPAuthorizationCredentials(scheme=scheme, credentials=credentials)

        fallback = request.headers.get("X-Access-Token")
        if fallback:
            logger.debug("Using X-Access-Token fallback header for authentication")
            return HTTPAuthorizationCredentials(scheme="X-Access-Token", credentials=fallback)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )


security = HTTPBearerOrHeader()


def _compare_secret(expected: str, provided: str) -> bool:
    return bool(expected) and hmac.compare_digest(expected, provided)


async def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    """Simple token validation without scopes."""
    token = credentials.credentials

    # Either in TOKEN_SCOPES map or matches MCP_ACCESS_TOKEN
    if http_settings._token_scopes_cache and token in http_settings._token_scopes_cache:
        return token

    if _compare_secret(http_settings.mcp_access_token, token):
        return token

    logger.warning("Authentication failed: invalid token provided")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing access token")


async def verify_token_with_scopes(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> Set[str]:
    """Validate token and return associated scopes."""
    token = await verify_token(credentials)
    return http_settings.resolve_scopes(token)
