"""
Is there a newer DV2Plex release on GitHub?

The desktop app updates from GitHub Releases instead of git: it asks once a day for the
latest release and tells the user, who downloads and installs it. Nothing is installed
automatically (the builds are not signed). The request goes to api.github.com and sends
nothing but the app name in the User-Agent.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple

REPOSITORY = "FutureMan0/DV2Plex"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
CACHE_SECONDS = 24 * 3600

_cache: Dict[str, Any] = {"at": 0.0, "result": None}


def parse_version(text: str) -> Optional[Tuple[int, int, int, Tuple[Any, ...]]]:
    """'v2.1.0' -> (2, 1, 0, ()); pre-releases ('2.1.0-rc.1') sort before the release."""
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", (text or "").strip())
    if not match:
        return None
    pre: Tuple[Any, ...] = ()
    if match.group(4):
        pre = tuple(int(p) if p.isdigit() else p for p in match.group(4).split("."))
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), pre


def is_newer(candidate: str, current: str) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    if not new or not old:
        return False
    if new[:3] != old[:3]:
        return new[:3] > old[:3]
    # Same numbers: a release beats its pre-releases
    if not new[3]:
        return bool(old[3])
    if not old[3]:
        return False
    return [str(p) for p in new[3]] > [str(p) for p in old[3]]


def fetch_latest(timeout: float = 6.0) -> Dict[str, Any]:
    request = urllib.request.Request(
        LATEST_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "DV2Plex-update-check"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def check(current: str, refresh: bool = False) -> Dict[str, Any]:
    """{current, latest, newer, url, notes, error}; cached for a day."""
    if not refresh and _cache["result"] and time.time() - _cache["at"] < CACHE_SECONDS:
        return dict(_cache["result"], current=current)
    result: Dict[str, Any] = {"current": current, "latest": None, "newer": False, "url": RELEASES_PAGE,
                              "notes": "", "error": None}
    try:
        data = fetch_latest()
        tag = str(data.get("tag_name") or "")
        result.update(
            latest=tag.lstrip("v") or None,
            newer=is_newer(tag, current),
            url=data.get("html_url") or RELEASES_PAGE,
            notes=(data.get("body") or "")[:4000],
        )
    except Exception as e:  # offline, rate limit, no release yet
        result["error"] = f"Could not reach GitHub: {e}"
    _cache.update(at=time.time(), result=result)
    return result
