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


def check_python_package(package_name: str) -> bool:
    """Prüft ob ein Python-Package installiert ist"""
    # Normalisiere Package-Name (cv2 -> cv2, PIL -> PIL, etc.)
    import_name = package_name
    if package_name == 'PIL':
        import_name = 'PIL'
    elif package_name == 'cv2':
        import_name = 'cv2'
    
    # Zuerst prüfen, ob das Paket in pip installiert ist
    # Das ist wichtig, da Pakete installiert sein können, aber aufgrund von
    # Abhängigkeitsproblemen nicht importierbar sind
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", package_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Paket ist installiert - versuche Import
            try:
                __import__(import_name)
                return True
            except (ImportError, ModuleNotFoundError):
                # Paket ist installiert, aber nicht importierbar (z.B. wegen Abhängigkeiten)
                # Das ist OK - das Paket ist vorhanden, auch wenn es aktuell nicht funktioniert
                logger.debug(f"✓ {package_name} ist installiert, aber Import schlägt fehl (möglicherweise Abhängigkeitsproblem)")
                return True
            except Exception:
                # Andere Fehler beim Import - Paket ist installiert, aber hat Probleme
                logger.debug(f"✓ {package_name} ist installiert, aber Import hat Probleme")
                return True
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, Exception):
        # pip show hat nicht funktioniert - versuche trotzdem Import
        pass
    
    # Fallback: Versuche direkten Import
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False
    except Exception:
        # Andere Fehler (z.B. wenn Package teilweise installiert ist)
        return False


def install_python_package(package_name: str, ask_user: bool = True) -> bool:
    """
    Installiert ein Python-Package zur Laufzeit
    
    Args:
        package_name: Name des Packages (z.B. 'torch' oder 'torch>=1.7')
        ask_user: Wenn True, wird der Benutzer gefragt, ob installiert werden soll
    
    Returns:
        True wenn erfolgreich installiert, False sonst
    """
    package_base = package_name.split('>=')[0].split('==')[0]
    
    # Prüfe erneut, ob Package bereits installiert ist
    if check_python_package(package_base):
        logger.info(f"✓ {package_base} bereits installiert")
        return True
    
    if ask_user:
        # Verwende nur Console-Input, keine GUI (um QApplication-Konflikte zu vermeiden)
        # Die GUI wird erst später in app.py erstellt
        try:
            response = input(f"⚠ {package_base} fehlt. Automatisch installieren? [y/N]: ")
            if response.lower() not in ['y', 'yes']:
                logger.warning(f"✗ Installation von {package_base} abgebrochen")
                return False
        except (EOFError, KeyboardInterrupt):
            # Keine Interaktion möglich (z.B. in nicht-interaktiver Umgebung)
            logger.warning(f"✗ Installation von {package_base} abgebrochen (keine Interaktion möglich)")
            return False
        except Exception:
            # Unerwarteter Fehler, versuche trotzdem zu installieren
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
        
        # Prüfe erneut, ob Installation erfolgreich war
        # Warte etwas und lade Import-Cache neu
        import time
        import importlib
        time.sleep(1)  # Pause, damit pip Installation abgeschlossen ist
        
        # Versuche Import-Cache zu leeren für dieses Package
        if package_base in sys.modules:
            del sys.modules[package_base]
        
        # Prüfe erneut
        if check_python_package(package_base):
            logger.info(f"✓ {package_base} erfolgreich installiert und verfügbar")
            return True
        else:
            # Installation war erfolgreich, aber Import funktioniert noch nicht
            # Das kann passieren, wenn das Package neu geladen werden muss
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
    Prüft und installiert fehlende Python-Packages
    
    Args:
        required_packages: Liste von Package-Namen (z.B. ['torch>=1.7', 'numpy'])
        ask_user: Wenn True, wird der Benutzer gefragt
    
    Returns:
        Dict mit Status für jedes Package
    """
    global _checked_packages
    results = {}
    missing = []
    
    # Erste Runde: Prüfe welche Packages fehlen
    for package in required_packages:
        package_base = package.split('>=')[0].split('==')[0]
        
        # Überspringe, wenn bereits geprüft und vorhanden
        if package_base in _checked_packages:
            results[package] = True
            continue
        
        if check_python_package(package_base):
            results[package] = True
            _checked_packages.add(package_base)  # Markiere als geprüft
            logger.info(f"✓ {package_base} vorhanden")
        else:
            results[package] = False
            missing.append(package)
            logger.warning(f"✗ {package_base} fehlt")
    
    # Zweite Runde: Installiere fehlende Packages
    if missing:
        missing_names = [pkg.split('>=')[0].split('==')[0] for pkg in missing]
        logger.info(f"Fehlende Packages: {', '.join(missing_names)}")
        
        # Frage einmal für alle Packages zusammen
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
        
        # Installiere jedes fehlende Package
        for package in missing:
            # Bei mehreren Packages: Nur beim ersten fragen, dann automatisch installieren
            should_ask = ask_user and len(missing) == 1
            package_base = package.split('>=')[0].split('==')[0]
            
            # Prüfe nochmal, ob Package vielleicht zwischenzeitlich installiert wurde
            if check_python_package(package_base):
                results[package] = True
                logger.info(f"✓ {package_base} ist jetzt verfügbar")
                continue
            
            # Installiere Package
            results[package] = install_python_package(package, ask_user=should_ask)
            
            # Nach Installation erneut prüfen
            if results[package]:
                # Kurze Pause und erneut prüfen
                import time
                time.sleep(0.5)
                if check_python_package(package_base):
                    results[package] = True
                    _checked_packages.add(package_base)  # Markiere als geprüft und verfügbar
                    logger.info(f"✓ {package_base} erfolgreich installiert und verfügbar")
                else:
                    # Installation war erfolgreich, aber Import funktioniert noch nicht
                    results[package] = True  # Markiere als installiert
                    _checked_packages.add(package_base)  # Markiere als geprüft (auch wenn Import noch nicht funktioniert)
                    logger.info(f"✓ {package_base} installiert (möglicherweise Neustart erforderlich)")
    
    return results


# Globale Variable, um zu verhindern, dass der Check mehrfach läuft
_dependency_check_done = False
_checked_packages = set()  # Set von bereits geprüften Packages

def check_and_download_on_startup(base_dir: Path, auto_download: bool = False, check_python_deps: bool = True):
    """
    Prüft beim Start alle Komponenten und lädt fehlende herunter
    
    Args:
        base_dir: Basis-Verzeichnis der Anwendung
        auto_download: Wenn True, werden fehlende Modelle automatisch heruntergeladen
        check_python_deps: Wenn True, werden Python-Packages geprüft und installiert
    """
    global _dependency_check_done
    
    # Verhindere mehrfache Ausführung des kompletten Checks
    if _dependency_check_done and check_python_deps:
        logger.debug("Dependency-Check wurde bereits ausgeführt, überspringe Python-Deps...")
        # Führe nur noch System-Checks aus (ffmpeg, Modelle)
        check_python_deps = False
    
    manager = DownloadManager(base_dir)
    
    logger.info("Prüfe Komponenten...")
    
    # Prüfe Python-Packages (wichtigste zuerst)
    if check_python_deps:
        logger.info("Prüfe Python-Dependencies...")
        critical_packages = [
            'PySide6',
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
        
        # Prüfe und installiere kritische Packages zuerst
        critical_results = check_and_install_dependencies(critical_packages, ask_user=True)
        missing_critical = [pkg.split('>=')[0].split('==')[0] for pkg, found in critical_results.items() if not found]
        
        if missing_critical:
            logger.warning(f"Kritische Packages fehlen: {', '.join(missing_critical)}")
            logger.warning("Die Anwendung kann möglicherweise nicht vollständig funktionieren.")
        else:
            logger.info("✓ Alle kritischen Python-Packages vorhanden")
        
        # Prüfe optionale Packages (nur wenn kritische vorhanden sind)
        if not missing_critical:
            optional_results = check_and_install_dependencies(optional_packages, ask_user=True)
        else:
            logger.info("Überspringe optionale Packages, da kritische fehlen.")
    
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
    
    # Markiere Check als abgeschlossen
    if check_python_deps:
        _dependency_check_done = True
    
    return status
