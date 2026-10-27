"""
dvgrab: finding the FireWire camera, building the command lines and starting the two
dvgrab processes DV2Plex uses:

- the recording one (-autosplit -t -f dv1), which writes one clip per scene
- the interactive one (-i), which only controls the camera (rewind, play, pause)

On Linux dvgrab needs root for /dev/raw1394 unless udev rules allow the user; then it runs
through `sudo -n`, and a keepalive refreshes the sudo timestamp during long captures.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from ..media import popen_kwargs
from .processes import default_use_sudo, drain_stream, read_all


class Dvgrab:
    """Command line, device and process start of dvgrab."""

    def __init__(
        self,
        command: List[str],
        use_sudo: Optional[bool],
        log: Callable[[str], None],
    ):
        self.command: List[str] = list(command) or ["dvgrab"]
        self.use_sudo = default_use_sudo() if use_sudo is None else bool(use_sudo)
        self.log = log
        self.last_command: Optional[List[str]] = None
        self.last_error: Optional[str] = None
        self._keepalive_stop: Optional[threading.Event] = None
        self._keepalive_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ device

    def detect_device(self) -> Optional[str]:
        """
        The first FireWire device: a card number ("0") from /sys/bus/firewire, a device path
        (/dev/raw1394), or card 0 if dvgrab exists at all. None without any of these.
        """
        try:
            firewire = Path("/sys/bus/firewire/devices")
            if firewire.exists():
                cards = []
                for entry in firewire.iterdir():
                    # fw0, fw1 are devices; fw1.0 are their units
                    if entry.name.startswith("fw") and "." not in entry.name and entry.is_dir():
                        try:
                            cards.append((int(entry.name[2:]), entry.name))
                        except ValueError:
                            continue
                if cards:
                    number, name = sorted(cards)[0]
                    self.log(f"FireWire-Gerät erkannt in /sys: {name} (Karte {number})")
                    return str(number)

            for device in ("/dev/raw1394", "/dev/video1394"):
                if Path(device).exists():
                    self.log(f"FireWire-Gerät gefunden: {device}")
                    return device

            if shutil.which(self.command[0]) or Path(self.command[0]).is_file():
                self.log("FireWire-Gerät: Verwende Standard-Karte 0")
                return "0"

            self.log("Kein FireWire-Gerät gefunden")
            return None
        except OSError as e:
            self.log(f"Fehler bei Geräteerkennung: {e}")
            return None

    @staticmethod
    def device_args(device: str) -> List[str]:
        """
        dvgrab arguments for the device: ["-card", "0"] for a card number, nothing for a device
        path (dvgrab finds /dev/raw1394 itself; its -i option means interactive, not input).
        """
        return ["-card", device] if device.isdigit() else []

    # ------------------------------------------------------------------ sudo

    def sudo_prefix(self) -> List[str]:
        """["sudo", "-n"] when dvgrab has to run as root, else []."""
        return ["sudo", "-n"] if self.use_sudo else []

    def start_sudo_keepalive(self) -> None:
        """Keeps the sudo timestamp fresh during long captures."""
        if not self.use_sudo or shutil.which("sudo") is None:
            return
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            return
        try:
            result = subprocess.run(["sudo", "-n", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            if result.returncode != 0:
                self.log("sudo Keepalive nicht möglich (kein sudo-Timestamp). Bitte Programm mit sudo starten.")
                return
        except (OSError, subprocess.TimeoutExpired) as e:
            self.log(f"sudo Keepalive konnte nicht geprüft werden: {e}")
            return

        stop = threading.Event()
        self._keepalive_stop = stop

        def keepalive() -> None:
            while not stop.wait(60):
                try:
                    subprocess.run(["sudo", "-n", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                except (OSError, subprocess.TimeoutExpired) as e:
                    self.log(f"sudo Keepalive fehlgeschlagen: {e}")
                    break

        self._keepalive_thread = threading.Thread(target=keepalive, daemon=True, name="SudoKeepalive")
        self._keepalive_thread.start()
        self.log("sudo Keepalive gestartet, um Root-Rechte während der Aufnahme zu halten.")

    def stop_sudo_keepalive(self) -> None:
        if self._keepalive_stop:
            self._keepalive_stop.set()
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=2)
        self._keepalive_thread = None
        self._keepalive_stop = None

    # ------------------------------------------------------------------ processes

    def _start(self, args: List[str], interactive: bool, label: str) -> Optional[subprocess.Popen]:
        cmd = self.sudo_prefix() + list(self.command) + args
        if self.use_sudo:
            self.log("HINWEIS: dvgrab benötigt root-Rechte. Versuche mit sudo...")
        self.log(f"dvgrab-Befehl: {' '.join(cmd)}")
        self.last_command = cmd
        self.last_error = None
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if interactive else None,
                # Unread output pipes fill up and block dvgrab: stdout is not read at all,
                # stderr by the capture monitor or a drain thread
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=0,
                **popen_kwargs(),
            )
        except OSError as e:
            self.log(f"Fehler beim Starten von {label}: {e}")
            self.last_error = f"{label} could not be started: {e}"
            return None

        # A dvgrab that ends within a second found no camera or no permission
        time.sleep(1)
        if process.poll() is None:
            return process
        output = read_all(process.stderr).strip()
        self.log(f"Fehler beim Starten von {label}: Return-Code {process.returncode}")
        if output:
            self.log(f"Fehler-Ausgabe: {output[:500]}")
        self.last_error = f"{label} ended right away (code {process.returncode})." + (
            f" Output: {output[-500:]}" if output else ""
        ) + _hint(output, self.use_sudo)
        return None

    def start_recording(self, device: str, splits_dir: Path, rewind: bool) -> Optional[subprocess.Popen]:
        """dvgrab with autosplit: one clip per scene, named after the recording time."""
        splits_dir.mkdir(parents=True, exist_ok=True)
        args = self.device_args(device)
        if rewind:
            args.append("-rewind")
        # dvgrab derives the container from the extension and appends the recording time
        args += ["-autosplit", "-t", "-f", "dv1", str(splits_dir / "dvgrab.avi")]
        self.log(f"Ausgabe-Verzeichnis: {splits_dir}")
        return self._start(args, interactive=False, label="dvgrab")

    def start_interactive(self, device: str) -> Optional[subprocess.Popen]:
        """dvgrab -i: reads single keys on stdin (a = rewind, p = play, k = pause, Esc = stop)."""
        self.start_sudo_keepalive()
        process = self._start(self.device_args(device) + ["-i"], interactive=True, label="interactive dvgrab")
        if process is not None:
            threading.Thread(target=drain_stream, args=(process.stderr,), daemon=True,
                             name="InteractiveDvgrabStderr").start()
            self.log("Interaktiver dvgrab gestartet (nur Steuerung)")
            self.log("Verfügbare Befehle: a=rewind, p=play, k=pause, Esc=stop")
        return process


def _hint(output: str, use_sudo: bool) -> str:
    """A next step for the usual reasons dvgrab ends right away."""
    text = output.lower()
    if "a password is required" in text or "a terminal is required" in text:
        return (" dvgrab needs root here and sudo asks for a password. Allow dvgrab in sudoers "
                "without a password, or start DV2Plex with ./run.sh --no-gui.")
    if "permission denied" in text:
        return " No permission for the FireWire device; add a udev rule or run with sudo."
    if "no camera" in text or "no such device" in text or "not found" in text:
        return " No camera answered. Connect it, switch it to playback (VCR) and check the cable."
    return ""
