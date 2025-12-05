# Projektstruktur-Übersicht

Diese Datei gibt einen schnellen Überblick über die reorganisierte Projektstruktur.

## Neue Struktur

```
dv2plex/
├── .github/                  # GitHub-Templates und Workflows
│   ├── ISSUE_TEMPLATE/       # Issue-Templates
│   └── PULL_REQUEST_TEMPLATE.md
│
├── dv2plex/                  # Haupt-Python-Package (unverändert)
│   ├── app.py
│   ├── config.py
│   ├── capture.py
│   └── ...
│
├── docs/                     # ✨ NEU: Alle Dokumentation
│   ├── BUILD_ANLEITUNG.md
│   ├── Upscaling_Profile_Referenz.md
│   ├── PROJEKTSTRUKTUR.md
│   └── STRUKTUR_ÜBERSICHT.md
│
├── scripts/                  # ✨ NEU: Build-Skripte
│   ├── build.sh
│   ├── build_pyinstaller.py
│   └── dv2plex.spec
│
├── config/                   # ✨ NEU: Konfigurationsbeispiele
│   └── examples/
│       └── Konfiguration_Beispiel.json
│
├── README.md                 # ✨ ÜBERARBEITET: Vollständige Open-Source-README
├── CONTRIBUTING.md           # ✨ NEU: Contributing-Richtlinien
├── LICENSE                   # ✨ NEU: MIT-Lizenz
├── CHANGELOG.md              # ✨ NEU: Änderungsprotokoll
└── requirements.txt
```

## Änderungen

### Neu erstellt

- **`docs/`**: Zentrale Dokumentation
- **`scripts/`**: Build-Skripte
- **`config/examples/`**: Konfigurationsbeispiele
- **`.github/`**: GitHub-Templates
- **`CONTRIBUTING.md`**: Contributing-Richtlinien
- **`LICENSE`**: MIT-Lizenz
- **`CHANGELOG.md`**: Änderungsprotokoll

### Verschoben

- `BUILD_ANLEITUNG.md` → `docs/BUILD_ANLEITUNG.md`
- `Upscaling_Profile_Referenz.md` → `docs/Upscaling_Profile_Referenz.md`
- `Konfiguration_Beispiel.json` → `config/examples/Konfiguration_Beispiel.json`
- `build.sh` → `scripts/build.sh`
- `build_pyinstaller.py` → `scripts/build_pyinstaller.py`
- `dv2plex.spec` → `scripts/dv2plex.spec`

### Überarbeitet

- **`README.md`**: Vollständige Open-Source-README mit:
  - Professionelle Formatierung
  - Badges
  - Detaillierte Installation
  - Contributing-Sektion
  - Credits
  - Roadmap

## Vorteile der neuen Struktur

1. **Sauberer**: Klare Trennung von Code, Docs, Scripts
2. **Wartbarer**: Einfacher zu navigieren und zu erweitern
3. **Professionell**: Open-Source-Standards eingehalten
4. **Dokumentiert**: Umfassende Dokumentation
5. **Contributor-freundlich**: Klare Richtlinien für Beiträge

## Nächste Schritte

1. GitHub-Repository erstellen
2. GitHub-URLs in README.md aktualisieren
3. Erste Version taggen
4. Releases erstellen
