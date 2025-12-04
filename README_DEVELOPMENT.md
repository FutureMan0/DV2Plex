# DV2Plex - Entwickler-Dokumentation

## Setup für Entwicklung

### 1. Python-Umgebung einrichten

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Externe Tools hinzufügen

#### ffmpeg
- Lade ffmpeg von https://ffmpeg.org/download.html
- Kopiere `ffmpeg.exe` nach `dv2plex/bin/ffmpeg.exe`

#### Real-ESRGAN
- Klone Real-ESRGAN Repository: `git clone https://github.com/xinntao/Real-ESRGAN.git`
- Kopiere den **gesamten** Real-ESRGAN-Ordner nach `dv2plex/bin/realesrgan/`
- Die Struktur sollte sein: `dv2plex/bin/realesrgan/inference_realesrgan_video.py`
- Installiere Real-ESRGAN Dependencies: `pip install -r requirements.txt`
- Modelle werden bei Bedarf automatisch heruntergeladen

### 3. DirectShow-Device konfigurieren

1. Führe `setup_device.bat` aus
2. Suche in der Ausgabe nach dem Namen deiner Kamera
3. Öffne `dv2plex/config/settings.json`
4. Trage den Device-Namen unter `device.dshow_video_device` ein

Beispiel:
```json
{
  "device": {
    "dshow_video_device": "JVC GR-D245"
  }
}
```

### 4. Anwendung starten

```bash
python -m dv2plex.app
```

oder

```bash
run.bat
```

## Projektstruktur

```
dv2plex/
  __init__.py          # Paket-Initialisierung
  app.py              # Hauptprogramm (GUI)
  config.py           # Konfigurations-Management
  capture.py          # Capture-Engine (ffmpeg)
  merge.py            # Merge-Engine (ffmpeg concat)
  upscale.py          # Upscale-Engine (Real-ESRGAN)
  plex_export.py      # Plex-Exporter
  bin/                # Externe Programme
  config/             # Konfigurationsdateien
  logs/               # Log-Dateien
  DV_Import/          # Arbeitsordner
  PlexMovies/         # Standard Plex-Root
```

## Workflow

1. **Preview**: Live-Vorschau der Kamera
2. **Capture**: DV-Aufnahme über DirectShow
3. **Merge**: Zusammenfügen mehrerer Parts
4. **Upscale**: 4K-Upscaling mit Real-ESRGAN
5. **Export**: Kopieren nach Plex-Library

## Konfiguration

Die Konfiguration wird in `dv2plex/config/settings.json` gespeichert.

Wichtige Einstellungen:
- `device.dshow_video_device`: DirectShow-Device-Name
- `paths.plex_movies_root`: Plex-Movies-Root-Ordner
- `upscaling.default_profile`: Standard-Upscaling-Profil
- `capture.auto_merge`: Automatisches Mergen nach Capture
- `capture.auto_upscale`: Automatisches Upscaling nach Merge
- `capture.auto_export`: Automatischer Export nach Upscaling

## Troubleshooting

### "ffmpeg nicht gefunden"
- Stelle sicher, dass `ffmpeg.exe` in `dv2plex/bin/` liegt
- Prüfe den Pfad in der Konfiguration

### "Real-ESRGAN nicht gefunden"
- Stelle sicher, dass der komplette Real-ESRGAN-Ordner in `dv2plex/bin/realesrgan/` liegt
- Prüfe ob `inference_realesrgan.py` vorhanden ist
- Prüfe ob die Pre-trained Models in `weights/` liegen

### "Kein Signal von Kamera"
- Prüfe FireWire-Verbindung
- Prüfe ob Kamera eingeschaltet ist
- Prüfe DirectShow-Device-Name in der Konfiguration
- Führe `setup_device.bat` aus, um verfügbare Geräte zu sehen

### Preview funktioniert nicht
- Prüfe ob ffmpeg den Device-Namen findet
- Versuche andere FPS-Einstellungen
- Prüfe FireWire-Treiber

## Logging

Log-Dateien werden in `dv2plex/logs/` gespeichert:
- Format: `dv2plex_YYYY-MM-DD.log`
- Enthält alle ffmpeg/Real-ESRGAN-Aufrufe und Fehler

## Build für Distribution

### PyInstaller (EXE-Bundle)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --add-data "dv2plex/bin;bin" dv2plex/app.py
```

**Wichtig**: Stelle sicher, dass `bin/ffmpeg/` und `bin/realesrgan/` im Build enthalten sind.

