"""
API token for the web server.

The token is created on the first start and kept as server.api_token in the settings; the
DV2PLEX_TOKEN environment variable takes precedence. Clients send it as the X-DV2Plex-Token
header, as "Authorization: Bearer <token>", or as ?token=... where no header can be set
(video and image URLs, the WebSocket, the first page load).

Which requests need it:
- the routes in ALWAYS_PROTECTED_PATHS (sudo, file system), whatever the bind host;
- every /api request and /ws when the server listens on more than the loopback interface.

Independent of the token, two checks keep other web pages out of a server on 127.0.0.1:
- the Host header has to name this machine (blocks DNS rebinding);
- a browser request that changes something, and the WebSocket, has to come from the page
  itself: its Origin has to match the Host (blocks cross-site requests).
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import secrets
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlsplit

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


LOOPBACK_HOST_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
# Methods a cross-site page must not trigger
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _host_name(host_header: str) -> str:
    """Host name of a Host header value, without port and IPv6 brackets, lower case."""
    value = (host_header or "").strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def host_allowed(host_header: Optional[str], loopback_only: bool, extra_hosts: Iterable[str] = ()) -> bool:
    """
    Whether a request with this Host header may reach the server.

    A server bound to the loopback interface only answers to names of this machine, so a web
    page cannot reach it through a DNS name that later resolves to 127.0.0.1 (DNS rebinding).
    A server on the network answers to any name; there every API request needs the token.
    """
    if not loopback_only:
        return True
    name = _host_name(host_header or "")
    if not name:
        return False
    allowed = {h.strip().lower() for h in extra_hosts if h and h.strip()}
    if name in LOOPBACK_HOST_NAMES or name in allowed:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def origin_allowed(origin: Optional[str], host_header: Optional[str]) -> bool:
    """
    Whether a request with this Origin header comes from the DV2Plex page itself.

    Browsers send Origin with cross-site requests, form posts and WebSocket handshakes.
    Scripts and curl usually send none; those are judged by the token rules alone.
    """
    if origin is None:
        return True
    origin = origin.strip()
    if not origin or origin == "null":
        return False
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return parts.netloc.lower() == (host_header or "").strip().lower()


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
