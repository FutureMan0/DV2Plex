# PyInstaller Build Guide for DV2Plex

This guide describes how to compile DV2Plex with PyInstaller into a standalone, executable file.

## Prerequisites

### 1. Python Environment

Make sure Python 3.8+ is installed:

```bash
python3 --version
```

### 2. Install Dependencies

Install all necessary Python packages:

```bash
pip install -r requirements.txt
```

### 3. External Tools

#### ffmpeg

ffmpeg must be installed separately:

**Linux:**
```bash
# Option 1: System package manager
sudo apt-get install ffmpeg  # Debian/Ubuntu
sudo yum install ffmpeg      # CentOS/RHEL

# Option 2: Static binary
# Download from: https://johnvansickle.com/ffmpeg/
# Extract to: dv2plex/bin/ffmpeg/
```

## Build Process

### Automatic Build

The easiest method is using the build script:

```bash
python build_pyinstaller.py
```

The script:
1. Checks all dependencies
2. Checks ffmpeg and models
3. Executes PyInstaller build
4. Copies additional files
5. Creates startup scripts

### Manual Build

If you want to perform the build manually:

```bash
# 1. Run PyInstaller
pyinstaller --clean --noconfirm dv2plex.spec

# 2. Result is located in: dist/DV2Plex/
```

## Build Result

After successful build, you will find the distribution in:

```
dist/DV2Plex/
├── DV2Plex              # Main executable (Linux/Mac)
├── DV2Plex.exe          # Main executable (Windows)
├── start.sh             # Startup script (Linux/Mac)
├── start.bat            # Startup script (Windows)
├── README.md            # Documentation
├── Konfiguration_Beispiel.json
└── [additional files and libraries]
```

## Distribution

The entire `dist/DV2Plex/` directory structure can be used as a standalone distribution.

**Important:**
- The distribution is platform-specific (Linux/Windows/macOS)
- ffmpeg must be installed separately (checked at startup)
- Real-ESRGAN models will be automatically downloaded on first start

## Troubleshooting

### "Module not found" Errors

If PyInstaller cannot find certain modules, add them to `hiddenimports` in `dv2plex.spec`:

```python
hiddenimports=[
    'missing_module',
    # ...
]
```

### Large File Size

The distribution can be very large (several GB) due to:
- PyTorch
- pywebview (Desktop Wrapper) + Web UI dependencies
- Real-ESRGAN dependencies

This is normal for a standalone distribution.

### ffmpeg not found

The application automatically checks for ffmpeg at startup. If not found:
1. Install ffmpeg system-wide, or
2. Place it in `dv2plex/bin/ffmpeg/`

### Models not downloading

Real-ESRGAN models are automatically downloaded on first use to:
- Linux/Mac: `~/.cache/realesrgan/`
- Windows: `%USERPROFILE%\.cache\realesrgan\`

If automatic download fails, download the models manually:
- RealESRGAN_x4plus.pth: https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth
- RealESRGAN_x4plus_anime_6B.pth: https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth

## Advanced Configuration

### Adding Icon

To add an icon for the executable, edit `dv2plex.spec`:

```python
exe = EXE(
    # ...
    icon='path/to/icon.ico',  # Windows
    icon='path/to/icon.icns',  # macOS
    # ...
)
```

### UPX Compression

UPX is used by default to reduce file size. If problems occur, it can be disabled:

```python
exe = EXE(
    # ...
    upx=False,
    # ...
)
```

## Platform-Specific Notes

### Linux

- Requires `libGL.so.1` and other X11 libraries
- Test on various distributions

## Support

If you encounter problems:
1. Check the logs in `logs/`
2. Run the application with `--debug` (if implemented)
3. Check the PyInstaller documentation: https://pyinstaller.org/
