# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spezifikation für DV2Plex
Erstellt eine vollständige, eigenständige Distribution
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
    ['start.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Konfigurationsdateien
        (str(dv2plex_dir / "config" / "settings.json"), "dv2plex/config"),
        (str(project_root / "config" / "examples" / "Konfiguration_Beispiel.json"), "."),
        
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
        
        # Basicsr (Real-ESRGAN Dependency)
        'basicsr',
        'basicsr.archs',
        'basicsr.archs.rrdbnet_arch',
        'basicsr.utils',
        'basicsr.utils.download_util',
        'basicsr.utils.registry',
        'basicsr.data',
        'basicsr.data.data_util',
        'basicsr.data.transforms',
        
        # PyTorch
        'torch',
        'torchvision',
        'torch.nn',
        'torch.utils',
        
        # OpenCV
        'cv2',
        
        # Andere wichtige Module
        'numpy',
        'PIL',
        'PIL.Image',
        'ffmpeg',
        'ffmpeg_python',
        'diffusers',
        'transformers',
        'accelerate',
        'safetensors',
        'facexlib',
        'gfpgan',
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
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DV2Plex',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Keine Konsole für GUI-Anwendung
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Kann später ein Icon hinzugefügt werden
)
