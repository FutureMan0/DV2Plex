"""
Starting, stopping and reading child processes (dvgrab, ffmpeg) the same way on Linux,
macOS and Windows.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import IO, Optional


def default_use_sudo() -> bool:
    """dvgrab needs root for /dev/raw1394 on Linux unless udev rules allow the user."""
    return sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() != 0


def interrupt_process(process: subprocess.Popen, timeout: float) -> None:
    """
    Stops a process the way Ctrl+C does, so dvgrab closes its current file cleanly.
    Windows has no SIGINT for child processes; there it is terminated.
    """
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            process.send_signal(signal.SIGINT)
        else:
            process.terminate()
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    except (OSError, ValueError):
        try:
            process.kill()
        except OSError:
            pass


def terminate_process(process: Optional[subprocess.Popen], timeout: float = 2.0) -> None:
    """terminate(), then kill() if it does not end in time."""
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    except OSError:
        pass


def drain_stream(stream: Optional[IO[bytes]]) -> None:
    """Reads a child's output pipe until it closes, so the child never blocks on a full pipe."""
    try:
        while stream and stream.read(4096):
            pass
    except (OSError, ValueError):
        pass


def read_all(stream: Optional[IO[bytes]]) -> str:
    """Whatever is left in a pipe, as text."""
    if not stream:
        return ""
    try:
        data = stream.read()
    except (OSError, ValueError):
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="ignore")
    return str(data or "")
