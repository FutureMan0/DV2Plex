# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spezifikation für DV2Plex (Linux)
Erstellt eine vollständige, eigenständige Linux-Distribution
"""

import os
import sys
from pathlib import Path

# Projekt-Root-Verzeichnis
project_root = Path(SPECPATH).parent
dv2plex_dir = project_root / "dv2plex"

block_cipher = None

# Sammle alle Python-Dateien aus dv2plex
dv2plex_py_files = []
for root, dirs, files in os.walk(dv2plex_dir):
    # Überspringe __pycache__ und .pyc Dateien
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for file in files:
        if file.endswith('.py'):
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, project_root)
            dv2plex_py_files.append(rel_path)

# Sammle alle Real-ESRGAN Python-Dateien
realesrgan_dir = dv2plex_dir / "bin" / "realesrgan"
realesrgan_py_files = []
if realesrgan_dir.exists():
    for root, dirs, files in os.walk(realesrgan_dir):
        dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', 'tests']]
        for file in files:
            if file.endswith('.py'):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, project_root)
                realesrgan_py_files.append(rel_path)

a = Analysis(
    [str(project_root / 'start.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Konfigurationsdateien
        (str(dv2plex_dir / "config" / "settings.json"), "dv2plex/config"),
        
        # Logo
        (str(project_root / "dv2plex_logo.png"), "."),
        
        # Real-ESRGAN Skripte und Module
        (str(realesrgan_dir / "inference_realesrgan_video.py"), "dv2plex/bin/realesrgan"),
        (str(realesrgan_dir / "inference_realesrgan.py"), "dv2plex/bin/realesrgan"),
        (str(realesrgan_dir / "realesrgan"), "dv2plex/bin/realesrgan/realesrgan"),
        
        # Real-ESRGAN Optionen
        (str(realesrgan_dir / "options"), "dv2plex/bin/realesrgan/options"),
    ],
    hiddenimports=[
        # PySide6 Module
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        
        # DV2Plex Module
        'dv2plex',
        'dv2plex.app',
        'dv2plex.config',
        'dv2plex.capture',
        'dv2plex.merge',
        'dv2plex.upscale',
        'dv2plex.plex_export',
        'dv2plex.frame_extraction',
        'dv2plex.cover_generation',
        
        # Real-ESRGAN Module
        'realesrgan',
        'realesrgan.archs',
        'realesrgan.archs.srvgg_arch',
        'realesrgan.archs.discriminator_arch',
        'realesrgan.models',
        'realesrgan.models.realesrgan_model',
        'realesrgan.models.realesrnet_model',
        'realesrgan.data',
        'realesrgan.data.realesrgan_dataset',
        'realesrgan.data.realesrgan_paired_dataset',
        'realesrgan.utils',
        
        # Basicsr (Real-ESRGAN Dependency) - wird zur Laufzeit installiert
        # 'basicsr',
        # 'basicsr.archs',
        # 'basicsr.archs.rrdbnet_arch',
        
        # PyTorch - wird zur Laufzeit installiert, nicht in PKG packen
        # 'torch',
        # 'torchvision',
        
        # OpenCV - wird zur Laufzeit installiert
        # 'cv2',
        
        # Andere wichtige Module - nur minimale Core-Module
        'numpy',  # Wird oft benötigt, aber klein
        'PIL',
        'PIL.Image',
        # 'ffmpeg',  # System-Tool, nicht Python-Package
        # 'ffmpeg_python',  # Wird zur Laufzeit installiert
        # 'diffusers',  # Wird zur Laufzeit installiert
        # 'transformers',  # Wird zur Laufzeit installiert
        # 'accelerate',  # Wird zur Laufzeit installiert
        # 'safetensors',  # Wird zur Laufzeit installiert
        # 'facexlib',  # Wird zur Laufzeit installiert
        # 'gfpgan',  # Wird zur Laufzeit installiert
        'tqdm',
        'yaml',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'scipy',
        'pandas',
        'jupyter',
        'notebook',
        'IPython',
        # Große Bibliotheken, die zur Laufzeit installiert werden können
        'torch',
        'torchvision',
        'nvidia.cuda_nvrtc',
        'nvidia.cuda_runtime',
        'nvidia.cudnn',
        'nvidia.cublas',
        'nvidia.cufft',
        'nvidia.curand',
        'nvidia.cusolver',
        'nvidia.cusparse',
        'nvidia.nccl',
        'nvidia.nvtx',
        'nvidia.nvjitlink',
        'nvidia.cufile',
        'triton',
    ],
    cipher=block_cipher,
    noarchive=True,  # True, um Größenprobleme mit großen Bibliotheken (PyTorch) zu vermeiden
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Verwende onedir Modus statt onefile, um Größenprobleme zu vermeiden
# Dependencies werden zur Laufzeit installiert/geprüft
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # Wichtig für onedir Modus
    name='DV2Plex',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # Keine Konsole für GUI-Anwendung
    disable_windowed_traceback=False,
    target_arch=None,
    icon=None,  # Optional: Icon für Linux-Desktop-Integration
)

# COLLECT für onedir Modus - erstellt ein Verzeichnis statt einer einzelnen Datei
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='DV2Plex',
)
