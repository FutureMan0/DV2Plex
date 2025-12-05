"""
Download-Manager für fehlende Komponenten
Wird beim Start der Anwendung ausgeführt, um fehlende Dependencies herunterzuladen
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
import urllib.request
import json
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class DownloadManager:
    """Verwaltet das Herunterladen fehlender Komponenten"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.bin_dir = base_dir / "dv2plex" / "bin"
        self.ffmpeg_dir = self.bin_dir / "ffmpeg"
        self.realesrgan_dir = self.bin_dir / "realesrgan"
        
    def check_ffmpeg(self) -> bool:
        """Prüft ob ffmpeg vorhanden ist"""
        # Prüfe lokales ffmpeg
        local_ffmpeg = self.ffmpeg_dir / "bin" / "ffmpeg"
        if local_ffmpeg.exists() and local_ffmpeg.is_file():
            logger.info(f"✓ ffmpeg gefunden: {local_ffmpeg}")
            return True
        
        # Prüfe System-ffmpeg
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            logger.info(f"✓ ffmpeg im System-PATH gefunden: {system_ffmpeg}")
            return True
        
        logger.warning("✗ ffmpeg nicht gefunden")
        return False
    
    def download_ffmpeg_info(self) -> Dict[str, Any]:
        """Gibt Informationen zum ffmpeg-Download zurück"""
        info = {
            "found": self.check_ffmpeg(),
            "download_urls": {
                "linux": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
                "windows": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
                "macos": "https://evermeet.cx/ffmpeg/ffmpeg-6.0.zip",
            },
            "instructions": {
                "linux": "Lade ffmpeg von johnvansickle.com herunter und extrahiere nach dv2plex/bin/ffmpeg",
                "windows": "Lade ffmpeg von gyan.dev herunter und extrahiere nach dv2plex/bin/ffmpeg",
                "macos": "Lade ffmpeg von evermeet.cx herunter oder installiere via Homebrew: brew install ffmpeg",
            }
        }
        return info
    
    def check_realesrgan_models(self) -> Dict[str, bool]:
        """Prüft welche Real-ESRGAN Modelle vorhanden sind"""
        # Modelle werden normalerweise in ~/.cache/realesrgan gespeichert
        cache_dir = Path.home() / ".cache" / "realesrgan"
        
        models = {
            "RealESRGAN_x4plus.pth": False,
            "RealESRGAN_x4plus_anime_6B.pth": False,
            "RealESRNet_x4plus.pth": False,
        }
        
        for model_name in models.keys():
            model_path = cache_dir / model_name
            if model_path.exists():
                models[model_name] = True
                logger.info(f"✓ Modell gefunden: {model_name}")
            else:
                logger.debug(f"✗ Modell fehlt: {model_name}")
        
        return models
    
    def download_realesrgan_model(self, model_name: str) -> bool:
        """Lädt ein Real-ESRGAN Modell herunter"""
        from basicsr.utils.download_util import load_file_from_url
        
        cache_dir = Path.home() / ".cache" / "realesrgan"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        model_path = cache_dir / model_name
        
        if model_path.exists():
            logger.info(f"Modell bereits vorhanden: {model_name}")
            return True
        
        # URLs für Modelle
        model_urls = {
            "RealESRGAN_x4plus.pth": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
            "RealESRGAN_x4plus_anime_6B.pth": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
            "RealESRNet_x4plus.pth": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.1/RealESRNet_x4plus.pth",
        }
        
        if model_name not in model_urls:
            logger.error(f"Unbekanntes Modell: {model_name}")
            return False
        
        try:
            logger.info(f"Lade Modell herunter: {model_name}")
            logger.info(f"URL: {model_urls[model_name]}")
            
            load_file_from_url(
                url=model_urls[model_name],
                model_dir=str(cache_dir),
                progress=True,
                file_name=model_name
            )
            
            if model_path.exists():
                logger.info(f"✓ Modell erfolgreich heruntergeladen: {model_name}")
                return True
            else:
                logger.error(f"✗ Download fehlgeschlagen: {model_name}")
                return False
                
        except Exception as e:
            logger.error(f"Fehler beim Download von {model_name}: {e}")
            return False
    
    def check_all(self) -> Dict[str, Any]:
        """Prüft alle Komponenten und gibt Status zurück"""
        status = {
            "ffmpeg": {
                "found": self.check_ffmpeg(),
                "info": self.download_ffmpeg_info(),
            },
            "realesrgan_models": self.check_realesrgan_models(),
        }
        return status
    
    def download_missing_models(self, auto_download: bool = False) -> Dict[str, bool]:
        """Lädt fehlende Modelle herunter"""
        models = self.check_realesrgan_models()
        results = {}
        
        for model_name, found in models.items():
            if not found:
                if auto_download:
                    results[model_name] = self.download_realesrgan_model(model_name)
                else:
                    results[model_name] = False
            else:
                results[model_name] = True
        
        return results


def check_and_download_on_startup(base_dir: Path, auto_download: bool = False):
    """
    Prüft beim Start alle Komponenten und lädt fehlende herunter
    
    Args:
        base_dir: Basis-Verzeichnis der Anwendung
        auto_download: Wenn True, werden fehlende Modelle automatisch heruntergeladen
    """
    manager = DownloadManager(base_dir)
    
    logger.info("Prüfe Komponenten...")
    status = manager.check_all()
    
    # Prüfe ffmpeg
    if not status["ffmpeg"]["found"]:
        logger.warning("ffmpeg nicht gefunden!")
        info = status["ffmpeg"]["info"]
        platform = sys.platform
        if platform.startswith("linux"):
            platform_key = "linux"
        elif platform.startswith("win"):
            platform_key = "windows"
        elif platform.startswith("darwin"):
            platform_key = "macos"
        else:
            platform_key = "linux"
        
        logger.info(f"Download-Anleitung: {info['instructions'].get(platform_key, 'Siehe README')}")
    
    # Prüfe Modelle
    missing_models = [name for name, found in status["realesrgan_models"].items() if not found]
    if missing_models:
        logger.info(f"Fehlende Modelle: {', '.join(missing_models)}")
        if auto_download:
            logger.info("Lade fehlende Modelle automatisch herunter...")
            results = manager.download_missing_models(auto_download=True)
            for model_name, success in results.items():
                if success:
                    logger.info(f"✓ {model_name} erfolgreich heruntergeladen")
                else:
                    logger.warning(f"✗ {model_name} konnte nicht heruntergeladen werden")
        else:
            logger.info("Modelle werden beim ersten Gebrauch automatisch heruntergeladen.")
    
    return status
