"""
Push notifications through ntfy (https://ntfy.sh).

Off unless notifications.ntfy_topic is set. On a public server anyone who knows the topic
can read its messages, so the topic should be hard to guess, or the server your own.
"""

import logging
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_NTFY_SERVER = "https://ntfy.sh"


def ntfy_url(config: Any) -> Optional[str]:
    """URL of the configured topic, or None when notifications are off."""
    topic = str(config.get("notifications.ntfy_topic", "") or "").strip()
    if not topic:
        return None
    server = str(config.get("notifications.ntfy_server", "") or DEFAULT_NTFY_SERVER).strip().rstrip("/")
    return f"{server}/{urllib.parse.quote(topic, safe='')}"


def send_ntfy(config: Any, message: str, log: Callable[[str], None]) -> bool:
    """Posts the message to the configured topic. Returns True if it was sent."""
    url = ntfy_url(config)
    if url is None:
        logger.debug("ntfy is off (notifications.ntfy_topic is empty), not sent: %s", message)
        return False
    try:
        request = urllib.request.Request(url, data=message.encode("utf-8"), method="POST")
        urllib.request.urlopen(request, timeout=5)
    except Exception as e:
        log(f"ntfy-Benachrichtigung fehlgeschlagen: {e}")
        return False
    log("ntfy notification sent.")
    return True
