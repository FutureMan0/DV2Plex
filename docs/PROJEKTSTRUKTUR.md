# Projektstruktur

Diese Datei beschreibt die Struktur des DV2Plex-Projekts.

## Verzeichnisstruktur

```
dv2plex/
├── dv2plex/                    # Haupt-Python-Package
│   ├── __init__.py            # Package-Initialisierung
│   ├── __main__.py            # Entry-Point für python -m dv2plex
│   ├── app.py                 # GUI-Hauptprogramm (PySide6)
│   ├── config.py              # Konfigurations-Management
│   ├── capture.py             # DV-Capture-Engine
│   ├── merge.py               # Video-Merge-Engine
│   ├── upscale.py             # Upscaling-Engine (Real-ESRGAN)
│   ├── plex_export.py         # Plex-Export-Engine
│   ├── frame_extraction.py    # Frame-Extraktion für Cover
│   ├── cover_generation.py    # Cover-Generierung (Stable Diffusion)
│   ├── download_manager.py   # Download-Manager für Dependencies
│   ├── config/                # Konfigurationsdateien
│   │   └── settings.json      # Standard-Konfiguration
│   └── bin/                   # Externe Binaries und Tools
│       └── realesrgan/         # Real-ESRGAN Repository (Submodule)
│
├── docs/                      # Dokumentation
│   ├── BUILD_ANLEITUNG.md     # PyInstaller Build-Anleitung
│   ├── Upscaling_Profile_Referenz.md  # Upscaling-Profile-Dokumentation
│   └── PROJEKTSTRUKTUR.md     # Diese Datei
│
├── scripts/                   # Build- und Utility-Skripte
│   ├── build.sh               # Shell-Skript für PyInstaller-Build
│   ├── build_pyinstaller.py   # Python-Build-Skript
│   └── dv2plex.spec          # PyInstaller-Spezifikation
│
├── config/                    # Konfigurationsbeispiele
│   └── examples/
│       └── Konfiguration_Beispiel.json
│
├── tests/                     # Tests (geplant)
│
├── .gitignore                # Git-Ignore-Regeln
├── LICENSE                   # MIT-Lizenz
├── README.md                 # Haupt-README
├── CONTRIBUTING.md           # Contributing-Richtlinien
├── CHANGELOG.md              # Änderungsprotokoll
├── requirements.txt          # Python-Dependencies
└── start.py                  # Direkter Startpunkt
```

## Wichtige Dateien

### Core-Module

- **`dv2plex/app.py`**: Haupt-GUI-Anwendung mit PySide6
- **`dv2plex/config.py`**: Zentrales Konfigurations-Management
- **`dv2plex/capture.py`**: DV-Capture mit ffmpeg
- **`dv2plex/merge.py`**: Zusammenfügen mehrerer Video-Parts
- **`dv2plex/upscale.py`**: KI-basiertes Upscaling
- **`dv2plex/plex_export.py`**: Export für Plex Media Server

### Konfiguration

- **`dv2plex/config/settings.json`**: Haupt-Konfigurationsdatei
- **`config/examples/Konfiguration_Beispiel.json`**: Beispiel-Konfiguration

### Dokumentation

- **`README.md`**: Haupt-Dokumentation
- **`CONTRIBUTING.md`**: Richtlinien für Beiträge
- **`docs/`**: Zusätzliche Dokumentation

### Build

- **`scripts/build.sh`**: Automatisiertes Build-Skript
- **`scripts/dv2plex.spec`**: PyInstaller-Konfiguration

## Module-Beschreibung

### app.py

Haupt-GUI-Anwendung mit:
- Modernem Liquid Glass Design
- Tab-basierter Navigation
- Live-Preview
- Workflow-Orchestrierung

### config.py

Konfigurations-Management:
- JSON-basierte Konfiguration
- Punkt-Notation für verschachtelte Werte
- Automatische Pfad-Auflösung
- Standard-Werte

### capture.py

DV-Capture-Engine:
- ffmpeg-Integration
- Multi-Part-Capture
- Live-Preview
- Fortschritts-Tracking

### merge.py

Video-Merge-Engine:
- Nahtloses Zusammenfügen
- Metadaten-Erhaltung
- Fehlerbehandlung

### upscale.py

Upscaling-Engine:
- Real-ESRGAN-Integration
- Mehrere Profile
- GPU-Unterstützung
- Fortschritts-Tracking

### plex_export.py

Plex-Export-Engine:
- Standard-Movie-Format
- Metadaten-Integration
- Ordnerstruktur

## Externe Dependencies

### Real-ESRGAN

Befindet sich in `dv2plex/bin/realesrgan/`:
- KI-basiertes Upscaling
- Video- und Bild-Upscaling
- Mehrere Modelle

### ffmpeg

Wird systemweit oder lokal benötigt:
- Video-Capture
- Video-Verarbeitung
- Encoding

## Build-Prozess

1. **Entwicklung**: `python -m dv2plex`
2. **Build**: `./scripts/build.sh`
3. **Distribution**: `dist/DV2Plex/`

## Erweiterungen

### Neue Features hinzufügen

1. Neues Modul in `dv2plex/` erstellen
2. In `app.py` integrieren
3. Dokumentation aktualisieren
4. Tests hinzufügen (geplant)

### Konfiguration erweitern

1. Neue Einträge in `settings.json` hinzufügen
2. `config.py` erweitern
3. Beispiel in `config/examples/` aktualisieren
