"""
API token for the web server.

The token is created on the first start and kept as server.api_token in the settings; the
DV2PLEX_TOKEN environment variable takes precedence. Clients send it as the X-DV2Plex-Token
header, as "Authorization: Bearer <token>", or as ?token=... where no header can be set
(video and image URLs, the WebSocket, the first page load).

Which requests need it:
- the routes in ALWAYS_PROTECTED_PATHS (sudo, file system), whatever the bind host;
- every /api request and /ws when the server listens on more than the loopback interface.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import secrets
from typing import Any, Mapping, Optional

TOKEN_ENV = "DV2PLEX_TOKEN"
TOKEN_SETTING = "server.api_token"
TOKEN_HEADER = "X-DV2Plex-Token"
TOKEN_QUERY = "token"

# Run sudo or expose the file system: never without the token.
ALWAYS_PROTECTED_PATHS = frozenset({
    "/api/browse",
    "/api/chown",
    "/api/fix-config-permissions",
    "/api/update/run",
})

_TOKEN_IN_URL = re.compile(r"([?&]token=)[^&\s\"']*")

logger = logging.getLogger(__name__)


def is_loopback(host: str) -> bool:
    """True if the bind host only accepts connections from this machine."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def token_from_environment() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


def load_or_create_token(config: Any) -> str:
    """Returns the API token, creating and saving one on the first start."""
    token = token_from_environment() or str(config.get(TOKEN_SETTING, "") or "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(24)
    config.set(TOKEN_SETTING, token)
    try:
        config.save_config()
    except OSError as e:
        logger.warning(
            "Could not save the new API token to %s (%s); it only lasts while this process runs. "
            "Run this as the user the server runs as, or set %s.", config.config_path, e, TOKEN_ENV,
        )
    return token


def requires_token(path: str, token_everywhere: bool) -> bool:
    """Whether a request to this path has to carry the token."""
    if path in ALWAYS_PROTECTED_PATHS:
        return True
    return token_everywhere and (path == "/ws" or path == "/api" or path.startswith("/api/"))


def token_from_request(headers: Mapping[str, str], query_params: Mapping[str, str]) -> Optional[str]:
    """Token sent with a request: header, bearer token or ?token=."""
    token = headers.get(TOKEN_HEADER)
    if token:
        return token
    authorization = headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return query_params.get(TOKEN_QUERY)


def token_matches(expected: Optional[str], given: Optional[str]) -> bool:
    if not expected or not given:
        return False
    return secrets.compare_digest(expected.encode("utf-8"), given.encode("utf-8"))


def redact_token(text: str) -> str:
    """Replaces ?token=... in a URL or log line."""
    return _TOKEN_IN_URL.sub(r"\1***", text)


class RedactTokenFilter(logging.Filter):
    """Keeps the token out of uvicorn's request and WebSocket log lines."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_token(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact_token(a) if isinstance(a, str) else a for a in record.args)
        return True
