#!/usr/bin/env python3
"""
Build-Skript für PyInstaller
Erstellt eine vollständige, eigenständige Distribution von DV2Plex
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
import urllib.request
import zipfile
import tarfile

# Projekt-Root
project_root = Path(__file__).parent
build_dir = project_root / "build"
dist_dir = project_root / "dist"

def check_dependencies():
    """Prüft ob alle notwendigen Dependencies installiert sind"""
    print("Prüfe Dependencies...")
    
    required_packages = [
        'PyInstaller',
        'PySide6',
        'torch',
        'torchvision',
        'basicsr',
        'facexlib',
        'gfpgan',
        'opencv-python',
        'numpy',
        'Pillow',
        'ffmpeg-python',
        'diffusers',
        'transformers',
        'accelerate',
        'safetensors',
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"  ✓ {package}")
        except ImportError:
            print(f"  ✗ {package} fehlt")
            missing.append(package)
    
    if missing:
        print(f"\nFehlende Packages: {', '.join(missing)}")
        print("Installiere mit: pip install " + " ".join(missing))
        return False
    
    return True

def download_ffmpeg():
    """Lädt ffmpeg herunter falls nicht vorhanden"""
    ffmpeg_dir = project_root / "dv2plex" / "bin" / "ffmpeg"
    ffmpeg_bin = ffmpeg_dir / "bin" / "ffmpeg"
    
    if ffmpeg_bin.exists():
        print(f"✓ ffmpeg bereits vorhanden: {ffmpeg_bin}")
        return True
    
    print("\nffmpeg nicht gefunden. Bitte manuell installieren:")
    print("  1. Lade ffmpeg von https://ffmpeg.org/download.html")
    print(f"  2. Extrahiere nach: {ffmpeg_dir}")
    print("  3. Stelle sicher, dass ffmpeg/bin/ffmpeg existiert")
    
    # Optional: Automatischer Download für Linux
    if sys.platform == "linux":
        print("\nVersuche automatischen Download für Linux...")
        try:
            # Beispiel-URL (muss angepasst werden)
            ffmpeg_url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
            print(f"Lade von: {ffmpeg_url}")
            # Hier könnte automatischer Download implementiert werden
            print("Automatischer Download noch nicht implementiert.")
        except Exception as e:
            print(f"Fehler beim Download: {e}")
    
    return False

def download_realesrgan_models():
    """Lädt Real-ESRGAN Modelle herunter falls nicht vorhanden"""
    models_dir = Path.home() / ".cache" / "realesrgan"
    model_files = [
        "RealESRGAN_x4plus.pth",
        "RealESRGAN_x4plus_anime_6B.pth",
    ]
    
    print("\nPrüfe Real-ESRGAN Modelle...")
    all_present = True
    
    for model_file in model_files:
        model_path = models_dir / model_file
        if model_path.exists():
            print(f"  ✓ {model_file}")
        else:
            print(f"  ✗ {model_file} fehlt")
            all_present = False
    
    if not all_present:
        print("\nModelle werden beim ersten Start automatisch heruntergeladen.")
        print(f"Oder manuell nach: {models_dir}")
    
    return True

def build_with_pyinstaller():
    """Führt PyInstaller Build aus"""
    print("\n" + "="*60)
    print("Starte PyInstaller Build...")
    print("="*60)
    
    spec_file = project_root / "scripts" / "dv2plex.spec"
    
    if not spec_file.exists():
        print(f"FEHLER: {spec_file} nicht gefunden!")
        return False
    
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_file)
    ]
    
    print(f"Befehl: {' '.join(cmd)}")
    print()
    
    try:
        result = subprocess.run(cmd, check=True, cwd=str(project_root))
        print("\n✓ Build erfolgreich!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n✗ Build fehlgeschlagen: {e}")
        return False

def copy_additional_files():
    """Kopiert zusätzliche Dateien in die Distribution"""
    print("\nKopiere zusätzliche Dateien...")
    
    dist_exe_dir = dist_dir / "DV2Plex"
    if not dist_exe_dir.exists():
        print(f"FEHLER: {dist_exe_dir} nicht gefunden!")
        return False
    
    # Kopiere README
    readme = project_root / "README.md"
    if readme.exists():
        shutil.copy2(readme, dist_exe_dir / "README.md")
        print(f"  ✓ README.md")
    
    # Kopiere Beispiel-Konfiguration
    config_example = project_root / "config" / "examples" / "Konfiguration_Beispiel.json"
    if config_example.exists():
        shutil.copy2(config_example, dist_exe_dir / "Konfiguration_Beispiel.json")
        print(f"  ✓ Konfiguration_Beispiel.json")
    
    # Erstelle Verzeichnisse für Output
    (dist_exe_dir / "DV_Import").mkdir(exist_ok=True)
    (dist_exe_dir / "logs").mkdir(exist_ok=True)
    
    print("  ✓ Verzeichnisse erstellt")
    
    return True

def create_startup_script():
    """Erstellt ein Startup-Skript für einfacheren Start"""
    print("\nErstelle Startup-Skripte...")
    
    dist_exe_dir = dist_dir / "DV2Plex"
    
    # Linux/Mac Shell-Skript
    startup_sh = dist_exe_dir / "start.sh"
    with open(startup_sh, 'w') as f:
        f.write("""#!/bin/bash
# DV2Plex Startup-Skript

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Führe die Anwendung aus
./DV2Plex "$@"
""")
    os.chmod(startup_sh, 0o755)
    print(f"  ✓ {startup_sh}")
    
    # Windows Batch-Datei
    startup_bat = dist_exe_dir / "start.bat"
    with open(startup_bat, 'w') as f:
        f.write("""@echo off
REM DV2Plex Startup-Skript

cd /d "%~dp0"
DV2Plex.exe %*
""")
    print(f"  ✓ {startup_bat}")
    
    return True

def main():
    """Hauptfunktion"""
    print("="*60)
    print("DV2Plex PyInstaller Build-Skript")
    print("="*60)
    
    # Prüfe Dependencies
    if not check_dependencies():
        print("\nBitte fehlende Dependencies installieren und erneut versuchen.")
        sys.exit(1)
    
    # Prüfe ffmpeg (optional, wird beim Start geprüft)
    download_ffmpeg()
    
    # Prüfe Modelle (optional, werden beim Start heruntergeladen)
    download_realesrgan_models()
    
    # Baue mit PyInstaller
    if not build_with_pyinstaller():
        sys.exit(1)
    
    # Kopiere zusätzliche Dateien
    copy_additional_files()
    
    # Erstelle Startup-Skripte
    create_startup_script()
    
    print("\n" + "="*60)
    print("Build abgeschlossen!")
    print("="*60)
    print(f"\nDistribution befindet sich in: {dist_dir / 'DV2Plex'}")
    print("\nHinweise:")
    print("  - ffmpeg muss separat installiert werden (falls nicht vorhanden)")
    print("  - Real-ESRGAN Modelle werden beim ersten Start automatisch heruntergeladen")
    print("  - Starte die Anwendung mit: ./DV2Plex oder start.sh/start.bat")
    print()

if __name__ == "__main__":
    main()
