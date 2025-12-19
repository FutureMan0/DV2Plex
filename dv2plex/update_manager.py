from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .config import Config
from .service import CaptureService


logger = logging.getLogger(__name__)


@dataclass
class UpdateStatus:
    """Status-Informationen über Git-Stand und letzten Check."""

    local: Optional[str]
    remote: Optional[str]
    ahead: int = 0
    behind: int = 0
    fetched: bool = False
    ok: bool = True
    error: Optional[str] = None
    last_checked: Optional[str] = None
    in_progress: bool = False
    blocked_reason: Optional[str] = None


class UpdateManager:
    """Verwaltet Git-Update-Checks und Pull + Service-Restart."""

    def __init__(
        self,
        repo_path: Path,
        branch: str,
        service_name: str,
        config: Config,
        capture_service: Optional[CaptureService] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.repo_path = repo_path
        self.branch = branch
        self.service_name = service_name
        self.config = config
        self.capture_service = capture_service
        self.log = log_callback or logger.info
        self._lock = asyncio.Lock()
        self._status: Optional[UpdateStatus] = None
        self._last_result: Optional[Dict[str, Any]] = None

    async def get_status(self, refresh: bool = False) -> UpdateStatus:
        if self._status is None or refresh:
            self._status = await asyncio.to_thread(self._refresh_status_sync)
        return self._status

    async def check_and_update(self, auto: bool = False) -> Dict[str, Any]:
        """Prüft auf neue Commits und führt ggf. Update aus."""
        async with self._lock:
            status = await self.get_status(refresh=True)
            status.in_progress = True
            busy_reason = self._busy_reason()
            if busy_reason:
                status.blocked_reason = busy_reason
                status.in_progress = False
                result = {
                    "updated": False,
                    "auto": auto,
                    "blocked": True,
                    "reason": busy_reason,
                    "status": status,
                }
                self._last_result = result
                return result

            if status.error:
                status.in_progress = False
                result = {
                    "updated": False,
                    "auto": auto,
                    "error": status.error,
                    "status": status,
                }
                self._last_result = result
                return result

            if status.behind <= 0:
                status.in_progress = False
                msg = "Bereits auf aktuellem Stand."
                self.log(msg)
                result = {"updated": False, "auto": auto, "message": msg, "status": status}
                self._last_result = result
                return result

            update_result = await asyncio.to_thread(self._perform_update_sync)
            status.in_progress = False
            if update_result.get("success"):
                self._status = await asyncio.to_thread(self._refresh_status_sync)
                msg = update_result.get("message", "Update durchgeführt.")
                self.log(msg)
            else:
                msg = update_result.get("error", "Update fehlgeschlagen.")
                self.log(msg)

            result = {"updated": update_result.get("success", False), "auto": auto, **update_result, "status": self._status}
            self._last_result = result
            return result

    def _busy_reason(self) -> Optional[str]:
        """Gibt den Grund zurück, warum kein Update möglich ist."""
        if not self.capture_service:
            return None
        try:
            if self.capture_service.is_capturing():
                return "Capture läuft"
            if hasattr(self.capture_service, "has_active_merge") and self.capture_service.has_active_merge():
                return "Merge läuft"
        except Exception:
            return "Capture-Status unbekannt"
        return None

    def _refresh_status_sync(self) -> UpdateStatus:
        now = datetime.utcnow().isoformat() + "Z"
        try:
            fetch = self._run_cmd(["git", "fetch", "origin", self.branch])
            fetched = fetch.returncode == 0
            if not fetched:
                error = fetch.stderr.strip() or "git fetch fehlgeschlagen"
                return UpdateStatus(
                    local=None,
                    remote=None,
                    ahead=0,
                    behind=0,
                    fetched=False,
                    ok=False,
                    error=error,
                    last_checked=now,
                )

            local = self._run_cmd(["git", "rev-parse", "HEAD"])
            remote = self._run_cmd(["git", "rev-parse", f"origin/{self.branch}"])

            ahead, behind, parse_error = self._parse_ahead_behind()

            status = UpdateStatus(
                local=local.stdout.strip() if local.returncode == 0 else None,
                remote=remote.stdout.strip() if remote.returncode == 0 else None,
                ahead=ahead,
                behind=behind,
                fetched=fetched,
                ok=parse_error is None and local.returncode == 0 and remote.returncode == 0,
                error=parse_error
                or (local.stderr.strip() if local.returncode != 0 else None)
                or (remote.stderr.strip() if remote.returncode != 0 else None),
                last_checked=now,
            )
            return status
        except Exception as exc:
            return UpdateStatus(
                local=None,
                remote=None,
                ahead=0,
                behind=0,
                fetched=False,
                ok=False,
                error=str(exc),
                last_checked=now,
            )

    def _parse_ahead_behind(self) -> tuple[int, int, Optional[str]]:
        """Parst git rev-list --left-right --count HEAD...origin/branch."""
        cmd = ["git", "rev-list", "--left-right", "--count", f"HEAD...origin/{self.branch}"]
        result = self._run_cmd(cmd)
        if result.returncode != 0:
            return 0, 0, result.stderr.strip() or "Konnte Ahead/Behind nicht ermitteln"
        try:
            parts = result.stdout.strip().split()
            if len(parts) != 2:
                return 0, 0, "Unerwartetes Format für Ahead/Behind"
            ahead = int(parts[0])
            behind = int(parts[1])
            return ahead, behind, None
        except Exception as exc:
            return 0, 0, f"Parsing-Fehler für Ahead/Behind: {exc}"

    def _perform_update_sync(self) -> Dict[str, Any]:
        """Führt git pull und Service-Restart aus."""
        pull_cmd = ["sudo", "git", "pull", "origin", self.branch]
        pull = self._run_cmd(pull_cmd, timeout=300)

        if pull.returncode != 0:
            return {
                "success": False,
                "error": pull.stderr.strip() or "git pull fehlgeschlagen",
                "stdout": pull.stdout.strip(),
                "stderr": pull.stderr.strip(),
            }

        enable_result = self._ensure_service_enabled()
        if not enable_result.get("success", False):
            return enable_result

        restart_result = self._restart_service()
        if not restart_result.get("success", False):
            return restart_result

        return {
            "success": True,
            "message": "Update erfolgreich: git pull + Service neu gestartet.",
            "stdout": pull.stdout.strip(),
        }

    def _ensure_service_enabled(self) -> Dict[str, Any]:
        """Aktiviert systemd-Service, falls nötig."""
        try:
            check = self._run_cmd(["systemctl", "is-enabled", self.service_name])
            if check.returncode == 0:
                return {"success": True, "message": "Service bereits aktiviert"}

            enable = self._run_cmd(["sudo", "systemctl", "enable", self.service_name])
            if enable.returncode != 0:
                return {
                    "success": False,
                    "error": enable.stderr.strip() or "systemctl enable fehlgeschlagen",
                    "stdout": enable.stdout.strip(),
                    "stderr": enable.stderr.strip(),
                }
            return {"success": True, "message": "Service aktiviert"}
        except Exception as exc:
            return {"success": False, "error": f"Service enable fehlgeschlagen: {exc}"}

    def _restart_service(self) -> Dict[str, Any]:
        """Startet den systemd-Service neu."""
        restart = self._run_cmd(["sudo", "systemctl", "restart", self.service_name])
        if restart.returncode != 0:
            return {
                "success": False,
                "error": restart.stderr.strip() or "Service-Restart fehlgeschlagen",
                "stdout": restart.stdout.strip(),
                "stderr": restart.stderr.strip(),
            }
        return {"success": True, "message": "Service neu gestartet"}

    def _run_cmd(self, cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
        """Führt Kommando im Repo aus."""
        return subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    @property
    def last_result(self) -> Optional[Dict[str, Any]]:
        return self._last_result

    def busy_reason(self) -> Optional[str]:
        """Öffentliche Abfrage des Busy-Status."""
        return self._busy_reason()


