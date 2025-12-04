# DV2Plex - MiniDV zu Plex Digitalisierungs-Tool

## Überblick

DV2Plex ist eine Windows-Anwendung zur Digitalisierung von MiniDV-Kassetten mit automatischem Upscaling und Export in Plex.

## Features

- **Live-Preview** der Kamera über DirectShow
- **DV-Capture** mit ffmpeg (mehrere Parts möglich)
- **Automatisches Mergen** mehrerer Capture-Parts
- **4K-Upscaling** mit Real-ESRGAN
- **Plex-Export** im Standard-Movie-Format

## Projektstruktur

Siehe `Ordnerstruktur.txt` für die vollständige Verzeichnisstruktur.

## Dokumentation

### Für Benutzer
- **[ANLEITUNG.md](ANLEITUNG.md)**: Vollständige Benutzer-Anleitung mit Schritt-für-Schritt-Anweisungen
- **[Upscaling_Profile_Referenz.md](Upscaling_Profile_Referenz.md)**: Detaillierte Übersicht aller Upscaling-Profile

### Für Entwickler
- **[Lastenheft.md](Lastenheft.md)**: Vollständige technische Spezifikation und Architektur
- **[README_DEVELOPMENT.md](README_DEVELOPMENT.md)**: Entwickler-Setup und Projektstruktur
- **[Ordnerstruktur.txt](Ordnerstruktur.txt)**: Detaillierte Verzeichnisstruktur
- **[Konfiguration_Beispiel.json](Konfiguration_Beispiel.json)**: Beispiel-Konfigurationsdatei

## Schnellstart

### 1. Installation

```bash
# Dependencies installieren
pip install -r requirements.txt

# Externe Tools hinzufügen:
# - ffmpeg.exe nach dv2plex/bin/ffmpeg/bin/ kopieren
# - Real-ESRGAN Repository nach dv2plex/bin/realesrgan/ klonen (siehe ANLEITUNG.md)
```

### 2. Kamera konfigurieren

```bash
# Device-Namen finden
setup_device.bat

# Device-Namen in dv2plex/config/settings.json eintragen
```

### 3. Anwendung starten

```bash
python -m dv2plex.app
# oder
run.bat
```

## Verwendung

Siehe **[ANLEITUNG.md](ANLEITUNG.md)** für detaillierte Anweisungen.

**Kurze Übersicht:**
1. Kamera über FireWire anschließen
2. Programm starten
3. Titel und Jahr eingeben
4. Preview starten (optional)
5. Aufnahme starten
6. Kassette manuell bedienen (Play drücken)
7. Aufnahme stoppen (oder bis Bandende warten)
8. Postprocessing läuft automatisch (Merge → Upscale → Plex-Export)

## Technische Details

Siehe `Lastenheft.md` für vollständige technische Dokumentation.

## Lizenz

[Lizenz hier eintragen]

