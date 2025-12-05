# PyInstaller Build-Anleitung für DV2Plex

Diese Anleitung beschreibt, wie DV2Plex mit PyInstaller zu einer eigenständigen, ausführbaren Datei kompiliert wird.

## Voraussetzungen

### 1. Python-Umgebung

Stelle sicher, dass Python 3.8+ installiert ist:

```bash
python3 --version
```

### 2. Dependencies installieren

Installiere alle notwendigen Python-Packages:

```bash
pip install -r requirements.txt
```

### 3. Externe Tools

#### ffmpeg

ffmpeg muss separat installiert werden:

**Linux:**
```bash
# Option 1: System-Package-Manager
sudo apt-get install ffmpeg  # Debian/Ubuntu
sudo yum install ffmpeg      # CentOS/RHEL

# Option 2: Statisches Binary
# Lade von: https://johnvansickle.com/ffmpeg/
# Extrahiere nach: dv2plex/bin/ffmpeg/
```

**Windows:**
- Lade von: https://www.gyan.dev/ffmpeg/builds/
- Extrahiere nach: `dv2plex/bin/ffmpeg/`
- Stelle sicher, dass `dv2plex/bin/ffmpeg/bin/ffmpeg.exe` existiert

**macOS:**
```bash
brew install ffmpeg
# Oder lade von: https://evermeet.cx/ffmpeg/
```

## Build-Prozess

### Automatischer Build

Das einfachste Verfahren ist die Verwendung des Build-Skripts:

```bash
python build_pyinstaller.py
```

Das Skript:
1. Prüft alle Dependencies
2. Prüft ffmpeg und Modelle
3. Führt PyInstaller Build aus
4. Kopiert zusätzliche Dateien
5. Erstellt Startup-Skripte

### Manueller Build

Falls du den Build manuell durchführen möchtest:

```bash
# 1. PyInstaller ausführen
pyinstaller --clean --noconfirm dv2plex.spec

# 2. Ergebnis befindet sich in: dist/DV2Plex/
```

## Build-Ergebnis

Nach erfolgreichem Build findest du die Distribution in:

```
dist/DV2Plex/
├── DV2Plex              # Haupt-Executable (Linux/Mac)
├── DV2Plex.exe          # Haupt-Executable (Windows)
├── start.sh             # Startup-Skript (Linux/Mac)
├── start.bat            # Startup-Skript (Windows)
├── README.md            # Dokumentation
├── Konfiguration_Beispiel.json
└── [weitere Dateien und Bibliotheken]
```

## Verteilung

Die gesamte `dist/DV2Plex/` Verzeichnisstruktur kann als eigenständige Distribution verwendet werden.

**Wichtig:**
- Die Distribution ist plattformspezifisch (Linux/Windows/macOS)
- ffmpeg muss separat installiert werden (wird beim Start geprüft)
- Real-ESRGAN Modelle werden beim ersten Start automatisch heruntergeladen

## Fehlerbehebung

### "Module nicht gefunden" Fehler

Falls PyInstaller bestimmte Module nicht findet, füge sie zu `hiddenimports` in `dv2plex.spec` hinzu:

```python
hiddenimports=[
    'fehlendes_modul',
    # ...
]
```

### Große Dateigröße

Die Distribution kann sehr groß sein (mehrere GB) aufgrund von:
- PyTorch
- PySide6
- Real-ESRGAN Dependencies

Dies ist normal für eine eigenständige Distribution.

### ffmpeg nicht gefunden

Die Anwendung prüft beim Start automatisch, ob ffmpeg vorhanden ist. Falls nicht:
1. Installiere ffmpeg systemweit, oder
2. Platziere es in `dv2plex/bin/ffmpeg/`

### Modelle werden nicht heruntergeladen

Real-ESRGAN Modelle werden automatisch beim ersten Gebrauch heruntergeladen nach:
- Linux/Mac: `~/.cache/realesrgan/`
- Windows: `%USERPROFILE%\.cache\realesrgan\`

Falls der automatische Download fehlschlägt, lade die Modelle manuell herunter:
- RealESRGAN_x4plus.pth: https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth
- RealESRGAN_x4plus_anime_6B.pth: https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth

## Erweiterte Konfiguration

### Icon hinzufügen

Um ein Icon für die Executable hinzuzufügen, bearbeite `dv2plex.spec`:

```python
exe = EXE(
    # ...
    icon='pfad/zum/icon.ico',  # Windows
    icon='pfad/zum/icon.icns',  # macOS
    # ...
)
```

### UPX Kompression

UPX wird standardmäßig verwendet, um die Dateigröße zu reduzieren. Falls Probleme auftreten, kann es deaktiviert werden:

```python
exe = EXE(
    # ...
    upx=False,
    # ...
)
```

## Plattform-spezifische Hinweise

### Linux

- Benötigt `libGL.so.1` und andere X11-Bibliotheken
- Teste auf verschiedenen Distributionen

### Windows

- Möglicherweise benötigt: Visual C++ Redistributable
- Antivirus-Software könnte die Executable blockieren (False Positive)

### macOS

- Möglicherweise benötigt: Code-Signing für Gatekeeper
- Erstelle ein .app Bundle für bessere Integration

## Support

Bei Problemen:
1. Prüfe die Logs in `logs/`
2. Führe die Anwendung mit `--debug` aus (falls implementiert)
3. Prüfe die PyInstaller-Dokumentation: https://pyinstaller.org/
