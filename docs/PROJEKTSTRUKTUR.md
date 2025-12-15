# Project Structure

This file describes the structure of the DV2Plex project.

## Directory Structure

```
dv2plex/
├── dv2plex/                    # Main Python package
│   ├── __init__.py            # Package initialization
│   ├── __main__.py            # Entry point for python -m dv2plex
│   ├── desktop_app.py         # Desktop launcher (pywebview)
│   ├── web_app.py             # FastAPI Web UI
│   ├── config.py              # Configuration management
│   ├── capture.py             # DV capture engine
│   ├── merge.py               # Video merge engine
│   ├── upscale.py             # Upscaling engine (Real-ESRGAN)
│   ├── plex_export.py         # Plex export engine
│   ├── frame_extraction.py    # Frame extraction for cover
│   ├── cover_generation.py    # Cover generation (Stable Diffusion)
│   ├── download_manager.py   # Download manager for dependencies
│   ├── config/                # Configuration files
│   │   └── settings.json      # Standard configuration
│   └── bin/                   # External binaries and tools
│       └── realesrgan/         # Real-ESRGAN repository (submodule)
│
├── docs/                      # Documentation
│   ├── BUILD_ANLEITUNG.md     # PyInstaller build guide
│   ├── Upscaling_Profile_Referenz.md  # Upscaling profile documentation
│   └── PROJEKTSTRUKTUR.md     # This file
│
├── scripts/                   # Build and utility scripts
│   ├── build.sh               # Shell script for PyInstaller build
│   ├── build_pyinstaller.py   # Python build script
│   └── dv2plex.spec          # PyInstaller specification
│
├── config/                    # Configuration examples
│   └── examples/
│       └── Konfiguration_Beispiel.json
│
├── tests/                     # Tests (planned)
│
├── .gitignore                # Git ignore rules
├── LICENSE                   # MIT license
├── README.md                 # Main README
├── CONTRIBUTING.md           # Contributing guidelines
├── CHANGELOG.md              # Changelog
├── requirements.txt          # Python dependencies
└── start.py                  # Direct entry point
```

## Important Files

### Core Modules

- **`dv2plex/desktop_app.py`**: Desktop application wrapper (pywebview)
- **`dv2plex/web_app.py`**: Web UI backend (FastAPI/uvicorn)
- **`dv2plex/config.py`**: Central configuration management
- **`dv2plex/capture.py`**: DV capture with ffmpeg
- **`dv2plex/merge.py`**: Merging multiple video parts
- **`dv2plex/upscale.py`**: AI-based upscaling
- **`dv2plex/plex_export.py`**: Export for Plex Media Server

### Configuration

- **`dv2plex/config/settings.json`**: Main configuration file
- **`config/examples/Konfiguration_Beispiel.json`**: Example configuration

### Documentation

- **`README.md`**: Main documentation
- **`CONTRIBUTING.md`**: Guidelines for contributions
- **`docs/`**: Additional documentation

### Build

- **`scripts/build.sh`**: Automated build script
- **`scripts/dv2plex.spec`**: PyInstaller configuration

## Module Description

### desktop_app.py

Desktop launcher that:
- Starts the local FastAPI/uvicorn server
- Opens the UI inside a pywebview window
- Shuts down the server when the window closes

### web_app.py

FastAPI-based Web UI with:
- Live preview (JPEG frames over WebSocket)
- Capture/post-processing control
- Status/log views

### config.py

Configuration management:
- JSON-based configuration
- Dot notation for nested values
- Automatic path resolution
- Default values

### capture.py

DV capture engine:
- ffmpeg integration
- Multi-part capture
- Live preview
- Progress tracking

### merge.py

Video merge engine:
- Seamless merging
- Metadata preservation
- Error handling

### upscale.py

Upscaling engine:
- Real-ESRGAN integration
- Multiple profiles
- GPU support
- Progress tracking

### plex_export.py

Plex export engine:
- Standard movie format
- Metadata integration
- Folder structure

## External Dependencies

### Real-ESRGAN

Located in `dv2plex/bin/realesrgan/`:
- AI-based upscaling
- Video and image upscaling
- Multiple models

### ffmpeg

Required system-wide or locally:
- Video capture
- Video processing
- Encoding

## Build Process

1. **Development**: `python -m dv2plex`
2. **Build**: `./scripts/build.sh`
3. **Distribution**: `dist/DV2Plex/`

## Extensions

### Adding New Features

1. Create new module in `dv2plex/`
2. Integrate in `app.py`
3. Update documentation
4. Add tests (planned)

### Extending Configuration

1. Add new entries to `settings.json`
2. Extend `config.py`
3. Update example in `config/examples/`
