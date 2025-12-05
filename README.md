# DV2Plex 🎬

<div align="center">

![DV2Plex Logo](https://img.shields.io/badge/DV2Plex-MiniDV%20Digitalisierung-blue?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey?style=for-the-badge)

**Professionelle Digitalisierung von MiniDV-Kassetten mit automatischem Upscaling und Plex-Export**

[Features](#-features) • [Installation](#-installation) • [Verwendung](#-verwendung) • [Entwicklung](#-entwicklung) • [Contributing](#-contributing) • [Credits](#-credits)

</div>

---

## 📖 Überblick

DV2Plex ist eine moderne, plattformübergreifende Anwendung zur Digitalisierung von MiniDV-Kassetten. Die Software kombiniert professionelle Video-Capture-Technologie mit KI-basiertem Upscaling und automatisiertem Export für Plex Media Server.

### Warum DV2Plex?

- 🎥 **Vollständiger Workflow**: Von der Aufnahme bis zum fertigen Plex-Export in einer Anwendung
- 🤖 **KI-Upscaling**: Automatisches Upscaling auf 4K mit Real-ESRGAN
- 🎨 **Moderne GUI**: Intuitive Benutzeroberfläche mit Live-Preview
- 🔄 **Automatisierung**: Automatisches Mergen, Upscaling und Exportieren
- 📦 **Plex-Integration**: Direkter Export im Plex-Standard-Format
- 🖼️ **Cover-Generierung**: Automatische Cover-Erstellung mit Stable Diffusion

---

## ✨ Features

### Core-Funktionen

- **Live-Preview**: Echtzeit-Vorschau der Kamera über DirectShow (Windows) oder v4l2 (Linux)
- **DV-Capture**: Professionelle Video-Aufnahme mit ffmpeg (mehrere Parts möglich)
- **Automatisches Mergen**: Nahtloses Zusammenfügen mehrerer Capture-Parts
- **4K-Upscaling**: KI-basiertes Upscaling mit Real-ESRGAN
- **Plex-Export**: Automatischer Export im Standard-Movie-Format
- **Cover-Generierung**: Automatische Cover-Erstellung mit Stable Diffusion

### Erweiterte Features

- **Mehrere Upscaling-Profile**: Von schnell bis höchste Qualität
- **Batch-Verarbeitung**: Verarbeitung mehrerer Videos gleichzeitig
- **Fortschrittsanzeige**: Detaillierte Fortschrittsanzeige für alle Prozesse
- **Logging**: Umfassendes Logging-System für Debugging
- **Konfigurierbar**: Flexible Konfiguration über JSON-Dateien

---

## 🚀 Installation

### Voraussetzungen

- **Python 3.8+**
- **ffmpeg** (wird beim Start geprüft)
- **FireWire-Kamera** oder DV-Device (für Capture)
- **GPU** empfohlen (für schnelleres Upscaling, optional)

### Schnellstart

#### 1. Repository klonen

```bash
git clone https://github.com/FutureMan0/ACR.git
cd dv2plex
```

#### 2. Dependencies installieren

```bash
pip install -r requirements.txt
```

#### 3. Externe Tools (optional)

**ffmpeg:**
- **Linux**: `sudo apt-get install ffmpeg` oder [statisches Binary](https://johnvansickle.com/ffmpeg/)

**Real-ESRGAN Modelle:**
Werden beim ersten Start automatisch heruntergeladen.

#### 4. Anwendung starten

```bash
python -m dv2plex
# oder
python start.py
```

### Build als eigenständige Anwendung

Siehe [docs/BUILD_ANLEITUNG.md](docs/BUILD_ANLEITUNG.md) für Details zum PyInstaller-Build.

```bash
./scripts/build.sh
```

---

## 📖 Verwendung

### Erste Schritte

1. **Kamera anschließen**: FireWire-Kamera über IEEE 1394 anschließen
2. **Programm starten**: `python -m dv2plex`
3. **Titel und Jahr eingeben**: Im Capture-Tab
4. **Preview starten** (optional): Zum Überprüfen der Verbindung
5. **Aufnahme starten**: Button "Aufnahme starten" klicken
6. **Kassette bedienen**: Play auf der Kamera drücken
7. **Aufnahme stoppen**: Button "Aufnahme stoppen" oder bis Bandende warten

### Workflow

```
Capture → Merge → Upscale → Plex-Export
```

Alle Schritte können automatisch oder manuell ausgeführt werden.

### Konfiguration

Die Konfiguration erfolgt über `dv2plex/config/settings.json`. Eine Beispiel-Konfiguration findest du in `config/examples/Konfiguration_Beispiel.json`.

**Wichtige Einstellungen:**

- `paths.ffmpeg_path`: Pfad zu ffmpeg (leer = System-PATH)
- `paths.realesrgan_path`: Pfad zu Real-ESRGAN (wird automatisch erkannt)
- `paths.plex_movies_root`: Zielverzeichnis für Plex-Export
- `upscaling.default_profile`: Standard-Upscaling-Profil

### Upscaling-Profile

Siehe [docs/Upscaling_Profile_Referenz.md](docs/Upscaling_Profile_Referenz.md) für eine vollständige Übersicht aller verfügbaren Profile.

**Verfügbare Profile:**
- `realesrgan_4x_hq`: Höchste Qualität (langsam)
- `realesrgan_4x_balanced`: Balance zwischen Qualität und Geschwindigkeit
- `realesrgan_4x_fast`: Schnell (geringere Qualität)
- `realesrgan_2x`: 2x Upscaling (sehr schnell)
- `ffmpeg_fast`: Nur ffmpeg-Upscaling (sehr schnell, niedrige Qualität)

---

## 🛠️ Entwicklung

### Projektstruktur

```
dv2plex/
├── dv2plex/              # Haupt-Python-Package
│   ├── app.py            # GUI-Hauptprogramm
│   ├── capture.py        # Capture-Engine
│   ├── merge.py          # Merge-Engine
│   ├── upscale.py        # Upscale-Engine
│   ├── plex_export.py    # Plex-Export
│   ├── config.py         # Konfigurations-Management
│   └── ...
├── docs/                 # Dokumentation
├── scripts/              # Build-Skripte
├── config/              # Konfigurationsbeispiele
└── tests/               # Tests (geplant)
```

### Setup für Entwicklung

```bash
# Repository klonen
git clone https://github.com/yourusername/dv2plex.git
cd dv2plex

# Virtual Environment erstellen
python -m venv venv
source venv/bin/activate  # Linux/Mac
# oder
venv\Scripts\activate  # Windows

# Dependencies installieren
pip install -r requirements.txt

# Entwicklung starten
python -m dv2plex
```

### Code-Stil

- **Python**: PEP 8
- **Type Hints**: Empfohlen für neue Funktionen
- **Docstrings**: Google-Style für alle öffentlichen Funktionen

### Tests

Tests sind geplant. Siehe [CONTRIBUTING.md](CONTRIBUTING.md) für Details.

---

## 🤝 Contributing

Wir freuen uns über Beiträge! Bitte lies zuerst [CONTRIBUTING.md](CONTRIBUTING.md) für Details.

### Wie kann ich beitragen?

- 🐛 **Bug Reports**: Erstelle ein Issue mit detaillierter Beschreibung
- 💡 **Feature Requests**: Diskutiere neue Features in Issues
- 📝 **Dokumentation**: Verbessere die Dokumentation
- 🔧 **Code**: Sende Pull Requests für Bugfixes oder Features
- 🎨 **UI/UX**: Verbesserungen an der Benutzeroberfläche
- 🌍 **Übersetzungen**: Übersetze die Anwendung in andere Sprachen

### Pull Request Prozess

1. Fork das Repository
2. Erstelle einen Feature-Branch (`git checkout -b feature/AmazingFeature`)
3. Committe deine Änderungen (`git commit -m 'Add some AmazingFeature'`)
4. Push zum Branch (`git push origin feature/AmazingFeature`)
5. Öffne einen Pull Request

---

## 📝 Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert. Siehe [LICENSE](LICENSE) für Details.

---

## 🙏 Credits

### Hauptentwickler

- **[Ihr Name]** - *Initialer Entwickler* - [GitHub](https://github.com/yourusername)

### Dependencies & Libraries

- **[PySide6](https://www.qt.io/qt-for-python/)** - GUI-Framework
- **[Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)** - KI-basiertes Upscaling
- **[ffmpeg](https://ffmpeg.org/)** - Video-Verarbeitung
- **[PyTorch](https://pytorch.org/)** - Deep Learning Framework
- **[Stable Diffusion](https://github.com/Stability-AI/stable-diffusion)** - Cover-Generierung

### Inspiration

- Real-ESRGAN von [Xinntao](https://github.com/xinntao)
- Plex Media Server Community

---

## 📊 Roadmap

### Geplante Features

- [ ] Batch-Verarbeitung mehrerer Kassetten
- [ ] Unterstützung für weitere Video-Formate
- [ ] Cloud-Export (Google Drive, Dropbox, etc.)
- [ ] Automatische Metadaten-Extraktion
- [ ] Unterstützung für weitere Upscaling-Modelle
- [ ] Plugin-System für Erweiterungen
- [ ] Web-Interface für Remote-Zugriff
- [ ] Automatische Kapitel-Erkennung

### Bekannte Probleme

Siehe [Issues](https://github.com/yourusername/dv2plex/issues) für bekannte Probleme und geplante Fixes.

---

## 📞 Support

### Hilfe bekommen

- 📖 **Dokumentation**: Siehe `docs/` Verzeichnis
- 💬 **Issues**: [GitHub Issues](https://github.com/yourusername/dv2plex/issues)
- 💡 **Diskussionen**: [GitHub Discussions](https://github.com/yourusername/dv2plex/discussions)

### Häufige Probleme

**ffmpeg nicht gefunden:**
- Installiere ffmpeg systemweit oder platziere es in `dv2plex/bin/ffmpeg/`

**Modelle werden nicht heruntergeladen:**
- Prüfe Internet-Verbindung
- Modelle werden in `~/.cache/realesrgan/` gespeichert

**Upscaling zu langsam:**
- Verwende ein schnelleres Profil (z.B. `realesrgan_2x`)
- GPU wird empfohlen für bessere Performance

---

## 🌟 Stars & Sponsoring

Wenn dir dieses Projekt gefällt, erwäge es mit einem ⭐ zu markieren!

---

## 📄 Changelog

Siehe [CHANGELOG.md](CHANGELOG.md) für eine vollständige Liste der Änderungen.

---

<div align="center">

**Made with ❤️ by the DV2Plex Community**

[⬆ Zurück nach oben](#dv2plex-)

</div>
