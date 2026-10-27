"""
One DV2Plex per settings folder.

Two desktop windows with their own servers would capture into the same folders and fight
over the camera. The running instance writes its port into instance.json next to the
settings; a second start finds it there and opens a window on it instead.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Optional

LOCK_NAME = "instance.json"


def _lock_path(config_dir: Path) -> Path:
    return Path(config_dir) / LOCK_NAME


def running_instance(config_dir: Path, timeout: float = 1.5) -> Optional[int]:
    """Port of a DV2Plex that answers on 127.0.0.1, or None."""
    path = _lock_path(config_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        port = int(data["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=timeout) as response:
            info = json.loads(response.read().decode("utf-8"))
        return port if "version" in info else None
    except Exception:
        return None


def claim(config_dir: Path, port: int) -> None:
    """Records this instance; release() removes the record again."""
    path = _lock_path(config_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass


def release(config_dir: Path) -> None:
    path = _lock_path(config_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid():
            path.unlink()
    except (OSError, ValueError):
        pass
