# WinDV Capture Bridge

Dieser Ordner enthält eine erste Version eines C++-Bindings für WinDV. Ziel ist es,
DV-Aufnahmen (inkl. Audio) direkt über DirectShow laufen zu lassen und die Ergebnisse
als Type‑2 AVI bereitzustellen, ohne ffmpeg für das eigentliche Capturing zu nutzen.

## Dateien

| Datei | Zweck |
| ----- | ----- |
| `WinDVCaptureBridge.h` | C-API, die von Python/ctypes geladen werden kann |
| `WinDVCaptureBridge.cpp` | Implementierung des Capture-Engines (DirectShow + WinDV Klassen) |

Die Bridge exportiert Funktionen zum Initialisieren, Setzen des Geräts, Starten und Stoppen
der Aufnahme sowie zum Abfragen von Fehlern. Die Aufnahme nutzt weiterhin die vorhandenen
WinDV-Klassen (`CDVInput`, `CMonitor`, `CDVQueue`, `CAVIWriter`), läuft aber ohne GUI.

## Bauen

1. Öffne das `WinDV.dsp`/`WinDV.vcxproj` Projekt (oder erstelle ein neues DLL-Projekt) in Visual Studio.
2. Füge die neuen Dateien `WinDVCaptureBridge.h/.cpp` hinzu.
3. Erstelle eine DLL, z. B. `WinDVCaptureBridge.dll`, mit der Definition `WINDV_CAPTURE_BUILD`
   (damit `__declspec(dllexport)` aktiv ist).
4. Stelle sicher, dass MFC (dynamisch) verlinkt wird, da die WinDV-Klassen darauf basieren.

## Verwendung

* `WindvBridge_Initialize()` – initialisiert COM/MFC.
* `WindvBridge_SetDevice(L"JVC GR-D245")` – setzt den DirectShow-Gerätenamen.
* `WindvBridge_SetPreviewWindow(hwnd)` – optionales Fensterhandle für die Vorschau.
* `WindvBridge_StartCapture(options)` – startet die Aufnahme.
* `WindvBridge_StopCapture()` – stoppt die Aufnahme.
* `WindvBridge_IsCapturing()` – liefert den aktuellen Status.
* `WindvBridge_LastError()` – gibt den zuletzt gesetzten Fehlertext zurück.
* `WindvBridge_Shutdown()` – fährt den Engine runter (ruft intern `CoUninitialize`).

Die Python-Seite lädt später diese DLL über `ctypes` (siehe geplanter `windv_bridge` Wrapper).



