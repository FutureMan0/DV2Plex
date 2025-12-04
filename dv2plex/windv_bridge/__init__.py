from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_DEFAULT_DLL = Path(__file__).resolve().parents[1] / "bin" / "windv" / "WinDVCaptureBridge.dll"


class WindvBridgeError(RuntimeError):
    """Fehler, die von der WinDV-Bridge gemeldet werden."""


class _CaptureOptions(ctypes.Structure):
    _fields_ = [
        ("output_directory", wintypes.LPCWSTR),
        ("file_base_name", wintypes.LPCWSTR),
        ("datetime_format", wintypes.LPCWSTR),
        ("numeric_suffix_digits", ctypes.c_int),
        ("type2_avi", wintypes.BOOL),
        ("enable_preview", wintypes.BOOL),
        ("queue_size", ctypes.c_int),
    ]


@dataclass
class CaptureConfig:
    output_directory: Path
    file_base_name: str = "part_001"
    datetime_format: str = "%Y%m%d_%H%M%S"
    numeric_suffix_digits: int = 3
    type2_avi: bool = True
    enable_preview: bool = True
    queue_size: int = 120


class WindvBridge:
    """Thin ctypes Wrapper um die C++ Bridge."""

    def __init__(self, dll_path: Optional[Path] = None):
        self._dll_path = Path(dll_path) if dll_path else _DEFAULT_DLL
        if not self._dll_path.exists():
            raise WindvBridgeError(f"WinDV Bridge DLL nicht gefunden: {self._dll_path}")
        self._dll = ctypes.WinDLL(str(self._dll_path))
        self._configure_prototypes()
        self._ensure_initialized()

    def _configure_prototypes(self) -> None:
        self._dll.WindvBridge_Initialize.restype = ctypes.c_int
        self._dll.WindvBridge_SetDevice.argtypes = [wintypes.LPCWSTR]
        self._dll.WindvBridge_SetDevice.restype = ctypes.c_int
        self._dll.WindvBridge_SetPreviewWindow.argtypes = [wintypes.HWND]
        self._dll.WindvBridge_SetPreviewWindow.restype = ctypes.c_int
        self._dll.WindvBridge_StartCapture.argtypes = [ctypes.POINTER(_CaptureOptions)]
        self._dll.WindvBridge_StartCapture.restype = ctypes.c_int
        self._dll.WindvBridge_StopCapture.restype = None
        self._dll.WindvBridge_IsCapturing.restype = ctypes.c_int
        self._dll.WindvBridge_LastError.restype = wintypes.LPCWSTR
        self._dll.WindvBridge_Shutdown.restype = None

    def _ensure_initialized(self) -> None:
        if self._dll.WindvBridge_Initialize() != 0:
            raise WindvBridgeError(self.last_error() or "Initialisierung fehlgeschlagen.")

    def set_device(self, device_name: str) -> None:
        if self._dll.WindvBridge_SetDevice(device_name) != 0:
            raise WindvBridgeError(self.last_error() or "Gerät konnte nicht gesetzt werden.")

    def set_preview_window(self, hwnd: int) -> None:
        if self._dll.WindvBridge_SetPreviewWindow(wintypes.HWND(hwnd)) != 0:
            raise WindvBridgeError(self.last_error() or "Preview-Fenster konnte nicht gesetzt werden.")

    def start_capture(self, config: CaptureConfig) -> None:
        options = _CaptureOptions(
            output_directory=str(config.output_directory),
            file_base_name=config.file_base_name,
            datetime_format=config.datetime_format,
            numeric_suffix_digits=config.numeric_suffix_digits,
            type2_avi=config.type2_avi,
            enable_preview=config.enable_preview,
            queue_size=config.queue_size,
        )
        if self._dll.WindvBridge_StartCapture(ctypes.byref(options)) != 0:
            raise WindvBridgeError(self.last_error() or "Aufnahme konnte nicht gestartet werden.")

    def stop_capture(self) -> None:
        self._dll.WindvBridge_StopCapture()

    def is_capturing(self) -> bool:
        return bool(self._dll.WindvBridge_IsCapturing())

    def last_error(self) -> str:
        message = self._dll.WindvBridge_LastError()
        return message or ""

    def shutdown(self) -> None:
        self._dll.WindvBridge_Shutdown()



