# Project Structure Overview

This file provides a quick overview of the reorganized project structure.

## New Structure

```
dv2plex/
├── .github/                  # GitHub templates and workflows
│   ├── ISSUE_TEMPLATE/       # Issue templates
│   └── PULL_REQUEST_TEMPLATE.md
│
├── dv2plex/                  # Main Python package (unchanged)
│   ├── app.py
│   ├── config.py
│   ├── capture.py
│   └── ...
│
├── docs/                     # ✨ NEW: All documentation
│   ├── BUILD_ANLEITUNG.md
│   ├── Upscaling_Profile_Referenz.md
│   ├── PROJEKTSTRUKTUR.md
│   └── STRUKTUR_ÜBERSICHT.md
│
├── scripts/                  # ✨ NEW: Build scripts
│   ├── build.sh
│   ├── build_pyinstaller.py
│   └── dv2plex.spec
│
├── config/                   # ✨ NEW: Configuration examples
│   └── examples/
│       └── Konfiguration_Beispiel.json
│
├── README.md                 # ✨ REVISED: Complete open-source README
├── CONTRIBUTING.md           # ✨ NEW: Contributing guidelines
├── LICENSE                   # ✨ NEW: MIT license
├── CHANGELOG.md              # ✨ NEW: Changelog
└── requirements.txt
```

## Changes

### Newly Created

- **`docs/`**: Central documentation
- **`scripts/`**: Build scripts
- **`config/examples/`**: Configuration examples
- **`.github/`**: GitHub templates
- **`CONTRIBUTING.md`**: Contributing guidelines
- **`LICENSE`**: MIT license
- **`CHANGELOG.md`**: Changelog

### Moved

- `BUILD_ANLEITUNG.md` → `docs/BUILD_ANLEITUNG.md`
- `Upscaling_Profile_Referenz.md` → `docs/Upscaling_Profile_Referenz.md`
- `Konfiguration_Beispiel.json` → `config/examples/Konfiguration_Beispiel.json`
- `build.sh` → `scripts/build.sh`
- `build_pyinstaller.py` → `scripts/build_pyinstaller.py`
- `dv2plex.spec` → `scripts/dv2plex.spec`

### Revised

- **`README.md`**: Complete open-source README with:
  - Professional formatting
  - Badges
  - Detailed installation
  - Contributing section
  - Credits
  - Roadmap

## Benefits of New Structure

1. **Cleaner**: Clear separation of code, docs, scripts
2. **Maintainable**: Easier to navigate and extend
3. **Professional**: Open-source standards followed
4. **Documented**: Comprehensive documentation
5. **Contributor-friendly**: Clear guidelines for contributions

## Next Steps

1. Create GitHub repository
2. Update GitHub URLs in README.md
3. Tag first version
4. Create releases
