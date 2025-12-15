"""
Download manager for missing components
Runs at application startup to download missing dependencies
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
    """Manages downloading of missing components"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.bin_dir = base_dir / "dv2plex" / "bin"
        self.ffmpeg_dir = self.bin_dir / "ffmpeg"
        self.realesrgan_dir = self.bin_dir / "realesrgan"
        
    def check_ffmpeg(self) -> bool:
        """Checks if ffmpeg is available"""
        # Check local ffmpeg
        local_ffmpeg = self.ffmpeg_dir / "bin" / "ffmpeg"
        if local_ffmpeg.exists() and local_ffmpeg.is_file():
            logger.info(f"✓ ffmpeg gefunden: {local_ffmpeg}")
            return True
        
        # Check system ffmpeg
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
        """Checks which Real-ESRGAN models are available"""
        # Models are usually stored in ~/.cache/realesrgan
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
        """Downloads a Real-ESRGAN model"""
        from basicsr.utils.download_util import load_file_from_url
        
        cache_dir = Path.home() / ".cache" / "realesrgan"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        model_path = cache_dir / model_name
        
        if model_path.exists():
            logger.info(f"Modell bereits vorhanden: {model_name}")
            return True
        
        # URLs for models
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
        """Checks all components and returns status"""
        status = {
            "ffmpeg": {
                "found": self.check_ffmpeg(),
                "info": self.download_ffmpeg_info(),
            },
            "realesrgan_models": self.check_realesrgan_models(),
        }
        return status
    
    def download_missing_models(self, auto_download: bool = False) -> Dict[str, bool]:
        """Downloads missing models"""
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


def check_python_package(package_name: str) -> bool:
    """Checks if a Python package is installed"""
    # Normalize package name (cv2 -> cv2, PIL -> PIL, etc.)
    import_name = package_name
    if package_name == 'PIL':
        import_name = 'PIL'
    elif package_name == 'cv2':
        import_name = 'cv2'
    elif package_name == 'pywebview':
        # pip name is pywebview, import name is webview
        import_name = 'webview'
    
    # First check if package is installed in pip
    # This is important because packages can be installed but not importable
    # due to dependency problems
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", package_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Package is installed - try import
            try:
                __import__(import_name)
                return True
            except (ImportError, ModuleNotFoundError):
                # Package is installed but not importable (e.g. due to dependencies)
                # This is OK - the package is present, even if it doesn't work currently
                logger.debug(f"✓ {package_name} ist installiert, aber Import schlägt fehl (möglicherweise Abhängigkeitsproblem)")
                return True
            except Exception:
                # Other errors during import - package is installed but has problems
                logger.debug(f"✓ {package_name} ist installiert, aber Import hat Probleme")
                return True
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, Exception):
        # pip show didn't work - try import anyway
        pass
    
    # Fallback: Try direct import
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False
    except Exception:
        # Other errors (e.g. if package is partially installed)
        return False


def install_python_package(package_name: str, ask_user: bool = True) -> bool:
    """
    Installs a Python package at runtime
    
    Args:
        package_name: Name of the package (e.g. 'torch' or 'torch>=1.7')
        ask_user: If True, user will be asked if installation should proceed
    
    Returns:
        True if successfully installed, False otherwise
    """
    package_base = package_name.split('>=')[0].split('==')[0]
    
    # Check again if package is already installed
    if check_python_package(package_base):
        logger.info(f"✓ {package_base} bereits installiert")
        return True
    
    if ask_user:
        # Use only console input, no GUI (to avoid QApplication conflicts)
        # GUI will be created later in app.py
        try:
            response = input(f"⚠ {package_base} fehlt. Automatisch installieren? [y/N]: ")
            if response.lower() not in ['y', 'yes']:
                logger.warning(f"✗ Installation von {package_base} abgebrochen")
                return False
        except (EOFError, KeyboardInterrupt):
            # No interaction possible (e.g. in non-interactive environment)
            logger.warning(f"✗ Installation von {package_base} abgebrochen (keine Interaktion möglich)")
            return False
        except Exception:
            # Unexpected error, try to install anyway
            logger.info(f"→ Installiere {package_base} automatisch...")
    
    try:
        logger.info(f"→ Installiere {package_name}...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package_name, "--quiet"],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"✗ Fehler beim Installieren von {package_name}: {result.stderr}")
            return False
        
        # Check again if installation was successful
        # Wait a bit and reload import cache
        import time
        import importlib
        time.sleep(1)  # Pause so pip installation can complete
        
        # Try to clear import cache for this package
        if package_base in sys.modules:
            del sys.modules[package_base]
        
        # Check again
        if check_python_package(package_base):
            logger.info(f"✓ {package_base} erfolgreich installiert und verfügbar")
            return True
        else:
            # Installation was successful but import doesn't work yet
            # This can happen if the package needs to be reloaded
            logger.info(f"✓ {package_base} installiert (wird beim nächsten Start verfügbar sein)")
            return True
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ Fehler beim Installieren von {package_name}: {e}")
        return False
    except Exception as e:
        logger.error(f"✗ Unerwarteter Fehler beim Installieren von {package_name}: {e}")
        return False


def check_and_install_dependencies(required_packages: list, ask_user: bool = True) -> dict:
    """
    Checks and installs missing Python packages
    
    Args:
        required_packages: List of package names (e.g. ['torch>=1.7', 'numpy'])
        ask_user: If True, user will be asked
    
    Returns:
        Dict with status for each package
    """
    global _checked_packages
    results = {}
    missing = []
    
    # First round: Check which packages are missing
    for package in required_packages:
        package_base = package.split('>=')[0].split('==')[0]
        
        # Skip if already checked and available
        if package_base in _checked_packages:
            results[package] = True
            continue
        
        if check_python_package(package_base):
            results[package] = True
            _checked_packages.add(package_base)  # Mark as checked
            logger.info(f"✓ {package_base} vorhanden")
        else:
            results[package] = False
            missing.append(package)
            logger.warning(f"✗ {package_base} fehlt")
    
    # Second round: Install missing packages
    if missing:
        missing_names = [pkg.split('>=')[0].split('==')[0] for pkg in missing]
        logger.info(f"Fehlende Packages: {', '.join(missing_names)}")
        
        # Ask once for all packages together
        if ask_user and len(missing) > 1:
            try:
                response = input(f"⚠ {len(missing)} Packages fehlen. Alle automatisch installieren? [y/N]: ")
                if response.lower() not in ['y', 'yes']:
                    logger.warning("✗ Installation abgebrochen")
                    for package in missing:
                        results[package] = False
                    return results
            except (EOFError, KeyboardInterrupt):
                logger.warning("✗ Installation abgebrochen (keine Interaktion möglich)")
                for package in missing:
                    results[package] = False
                return results
        
        # Install each missing package
        for package in missing:
            # With multiple packages: Only ask for the first, then install automatically
            should_ask = ask_user and len(missing) == 1
            package_base = package.split('>=')[0].split('==')[0]
            
            # Check again if package was maybe installed in the meantime
            if check_python_package(package_base):
                results[package] = True
                logger.info(f"✓ {package_base} ist jetzt verfügbar")
                continue
            
            # Install package
            results[package] = install_python_package(package, ask_user=should_ask)
            
            # Check again after installation
            if results[package]:
                # Short pause and check again
                import time
                time.sleep(0.5)
                if check_python_package(package_base):
                    results[package] = True
                    _checked_packages.add(package_base)  # Mark as checked and available
                    logger.info(f"✓ {package_base} erfolgreich installiert und verfügbar")
                else:
                    # Installation was successful but import doesn't work yet
                    results[package] = True  # Mark as installed
                    _checked_packages.add(package_base)  # Mark as checked (even if import doesn't work yet)
                    logger.info(f"✓ {package_base} installiert (möglicherweise Neustart erforderlich)")
    
    return results


# Global variable to prevent the check from running multiple times
_dependency_check_done = False
_checked_packages = set()  # Set of already checked packages

def check_and_download_on_startup(base_dir: Path, auto_download: bool = False, check_python_deps: bool = True):
    """
    Checks all components at startup and downloads missing ones
    
    Args:
        base_dir: Base directory of the application
        auto_download: If True, missing models will be downloaded automatically
        check_python_deps: If True, Python packages will be checked and installed
    """
    global _dependency_check_done
    
    # Prevent multiple executions of the complete check
    if _dependency_check_done and check_python_deps:
        logger.debug("Dependency check was already executed, skipping Python deps...")
        # Only run system checks (ffmpeg, models)
        check_python_deps = False
    
    manager = DownloadManager(base_dir)
    
    logger.info("Checking components...")
    
    # Check Python packages (most important first)
    if check_python_deps:
        logger.info("Prüfe Python-Dependencies...")
        critical_packages = [
            'pywebview',
            'torch',
            'torchvision',
            'numpy',
            'PIL',
            'cv2',
        ]
        
        optional_packages = [
            'basicsr',
            'facexlib',
            'gfpgan',
            'diffusers',
            'transformers',
        ]
        
        # Check and install critical packages first
        critical_results = check_and_install_dependencies(critical_packages, ask_user=True)
        missing_critical = [pkg.split('>=')[0].split('==')[0] for pkg, found in critical_results.items() if not found]
        
        if missing_critical:
            logger.warning(f"Kritische Packages fehlen: {', '.join(missing_critical)}")
            logger.warning("Die Anwendung kann möglicherweise nicht vollständig funktionieren.")
        else:
            logger.info("✓ Alle kritischen Python-Packages vorhanden")
        
        # Check optional packages (only if critical ones are present)
        if not missing_critical:
            optional_results = check_and_install_dependencies(optional_packages, ask_user=True)
        else:
            logger.info("Überspringe optionale Packages, da kritische fehlen.")
    
    status = manager.check_all()
    
    # Check ffmpeg
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
    
    # Check models
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
    
    # Mark check as completed
    if check_python_deps:
        _dependency_check_done = True
    
    return status
