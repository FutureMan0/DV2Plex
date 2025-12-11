"""
Konfigurations-Management für DV2Plex
"""

import json
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional


class Config:
    """Verwaltet die Konfiguration der Anwendung"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialisiert die Konfiguration
        
        Args:
            config_path: Pfad zur Konfigurationsdatei. Wenn None, wird Standardpfad verwendet.
        """
        self.base_dir = Path(__file__).parent.parent
        self.config_dir = self.base_dir / "dv2plex" / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        if config_path is None:
            self.config_path = self.config_dir / "settings.json"
        else:
            self.config_path = Path(config_path)
        
        self.default_config = self._get_default_config()
        self.config = self._load_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Erstellt die Standard-Konfiguration"""
        base_dir = Path(__file__).parent.parent
        dv2plex_dir = base_dir / "dv2plex"
        
        # Linux-Pfade (ohne .exe)
        ffmpeg_default = shutil.which("ffmpeg") or str(dv2plex_dir / "bin" / "ffmpeg")
        
        # Linux Standard-Pfade
        home_dir = Path.home()
        
        return {
            "version": "1.0",
            "paths": {
                "plex_movies_root": str(home_dir / "Plex" / "Movies"),
                "dv_import_root": str(dv2plex_dir / "DV_Import"),
                "ffmpeg_path": "",  # Leer = System-PATH verwenden
                "realesrgan_path": ""  # Leer = System-PATH verwenden
            },
            "device": {
                "firewire_device": ""  # Leer = Auto-Detection
            },
            "upscaling": {
                "default_profile": "realesrgan_2x",
                "profiles": {
                    "realesrgan_4x_hq": {
                        "backend": "realesrgan",
                        "scale_factor": 4,
                        "model": "RealESRGAN_x4plus",
                        "face_enhance": False,
                        "tile_size": 400,
                        "tile_pad": 10,
                        "encoder": "libx264",
                        "encoder_options": {
                            "crf": 17,
                            "preset": "veryfast",
                            "tune": "film"
                        }
                    },
                    "realesrgan_4x_balanced": {
                        "backend": "realesrgan",
                        "scale_factor": 4,
                        "model": "RealESRGAN_x4plus",
                        "face_enhance": False,
                        "tile_size": 400,
                        "tile_pad": 10,
                        "encoder": "libx264",
                        "encoder_options": {
                            "crf": 18,
                            "preset": "veryfast",
                            "tune": "film"
                        }
                    },
                    "realesrgan_4x_fast": {
                        "backend": "realesrgan",
                        "scale_factor": 4,
                        "model": "RealESRGAN_x4plus",
                        "face_enhance": False,
                        "tile_size": 400,
                        "tile_pad": 10,
                        "encoder": "libx264",
                        "encoder_options": {
                            "crf": 20,
                            "preset": "veryfast",
                            "tune": "film"
                        }
                    },
                    "realesrgan_2x": {
                        "backend": "realesrgan",
                        "scale_factor": 2,
                        "model": "RealESRGAN_x4plus",
                        "face_enhance": False,
                        "tile_size": 400,
                        "tile_pad": 10,
                        "encoder": "libx264",
                        "encoder_options": {
                            "crf": 18,
                            "preset": "slow",
                            "tune": "film"
                        }
                    },
                    "ffmpeg_fast": {
                        "backend": "ffmpeg",
                        "scale_factor": 4,
                        "encoder": "libx264",
                        "encoder_options": {
                            "crf": 20,
                            "preset": "veryfast",
                            "tune": "film"
                        }
                    }
                }
            },
            "capture": {
                "auto_merge": True,
                "auto_upscale": True,
                "auto_export": False,
                "auto_postprocess": False,
                "auto_rewind_play": True,
                "timestamp_overlay": True,
                "timestamp_duration": 4
            },
            "ui": {
                "window_width": 1280,
                "window_height": 720,
                "preview_fps": 10
            },
            "logging": {
                "level": "INFO",
                "log_directory": str(dv2plex_dir / "logs"),
                "max_log_files": 10
            },
            "update": {
                "enabled": True,
                "interval_minutes": 60,
                "branch": "master",
                "service_name": "dv2plex",
                "skip_during_capture": True,
                "skip_during_merge": True
            },
            "cover": {
                "default_model": "runwayml/stable-diffusion-v1-5",
                "default_prompt": "cinematic movie poster, dramatic lighting, vintage film look, high detail, professional photography",
                "strength": 0.6,
                "guidance_scale": 8.0,
                "output_size": "1000x1500",
                "num_inference_steps": 50
            }
        }
    
    def _load_config(self) -> Dict[str, Any]:
        """Lädt die Konfiguration aus der Datei oder erstellt Standard-Konfiguration"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                # Merge mit Defaults für fehlende Schlüssel
                merged = self._merge_dicts(self.default_config, config)
                # Migriere Windows-Pfade zu Linux-Pfaden
                merged = self._migrate_windows_paths(merged)
                return merged
            except Exception as e:
                print(f"Fehler beim Laden der Konfiguration: {e}")
                return self.default_config.copy()
        else:
            # Erstelle Standard-Konfiguration
            self.save_config(self.default_config)
            return self.default_config.copy()
    
    def _migrate_windows_paths(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Migriert Windows-Pfade zu Linux-Standard-Pfaden"""
        import os
        home_dir = Path.home()
        
        # Prüfe ob wir auf Linux sind
        if os.name != 'posix':
            return config  # Keine Migration auf Windows
        
        paths = config.get("paths", {})
        migrated = False
        
        # Plex Movies Root: Wenn Windows-Pfad, auf Linux-Standard setzen
        plex_root = paths.get("plex_movies_root", "")
        if plex_root and ("C:\\" in plex_root or "C:/" in plex_root):
            paths["plex_movies_root"] = str(home_dir / "Plex" / "Movies")
            migrated = True
        elif plex_root and plex_root.startswith("~"):
            # Expandiere ~ zu vollständigem Pfad
            paths["plex_movies_root"] = str(Path(plex_root).expanduser())
            migrated = True
        
        # DV Import Root: Wenn Windows-Pfad, auf Linux-Standard setzen
        dv_root = paths.get("dv_import_root", "")
        if dv_root and ("C:\\" in dv_root or "C:/" in dv_root):
            paths["dv_import_root"] = str(self.base_dir / "dv2plex" / "DV_Import")
            migrated = True
        
        # ffmpeg Path: Wenn Windows-Pfad oder .exe, auf leer setzen (System-PATH)
        ffmpeg_path = paths.get("ffmpeg_path", "")
        if ffmpeg_path and (".exe" in ffmpeg_path or "C:\\" in ffmpeg_path or "C:/" in ffmpeg_path):
            paths["ffmpeg_path"] = ""
            migrated = True
        
        # RealESRGAN Path: Wenn Windows-Pfad, auf leer setzen (System-PATH)
        realesrgan_path = paths.get("realesrgan_path", "")
        if realesrgan_path and ("C:\\" in realesrgan_path or "C:/" in realesrgan_path):
            paths["realesrgan_path"] = ""
            migrated = True
        
        # Entferne auto_detect_device aus device (nicht mehr benötigt)
        device = config.get("device", {})
        if "auto_detect_device" in device:
            del device["auto_detect_device"]
            migrated = True
        
        # Entferne dshow_video_device (Windows-spezifisch)
        if "dshow_video_device" in device:
            del device["dshow_video_device"]
            migrated = True
        
        # Speichere migrierte Config
        if migrated:
            config["paths"] = paths
            config["device"] = device
            self.save_config(config)
        
        return config
    
    def _merge_dicts(self, default: Dict, user: Dict) -> Dict:
        """Merge zwei verschachtelte Dictionaries"""
        result = default.copy()
        for key, value in user.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_dicts(result[key], value)
            else:
                result[key] = value
        return result
    
    def save_config(self, config: Optional[Dict[str, Any]] = None):
        """Speichert die Konfiguration"""
        if config is None:
            config = self.config
        
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Holt einen Wert aus der Konfiguration mit Punkt-Notation
        
        Args:
            key_path: Pfad zum Wert, z.B. "paths.ffmpeg_path"
            default: Standardwert, falls nicht gefunden
        
        Returns:
            Der Wert oder default
        """
        keys = key_path.split('.')
        value = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value
    
    def set(self, key_path: str, value: Any):
        """
        Setzt einen Wert in der Konfiguration mit Punkt-Notation
        
        Args:
            key_path: Pfad zum Wert, z.B. "paths.ffmpeg_path"
            value: Der zu setzende Wert
        """
        keys = key_path.split('.')
        config = self.config
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            config = config[key]
        config[keys[-1]] = value
    
    def get_ffmpeg_path(self) -> Path:
        """Gibt den Pfad zu ffmpeg zurück"""
        path = self.get("paths.ffmpeg_path", "")
        if path and path.strip():
            return Path(path)
        # Leer = Suche ffmpeg im System-PATH
        import shutil
        ffmpeg_system = shutil.which("ffmpeg")
        if ffmpeg_system:
            return Path(ffmpeg_system)
        return Path("ffmpeg")  # Verwende System-PATH
    
    def get_realesrgan_path(self) -> Path:
        """Gibt den Pfad zu inference_realesrgan_video.py zurück"""
        path = self.get("paths.realesrgan_path", "")
        if path and path.strip():
            return Path(path)
        # Leer = Suche im System-PATH
        import shutil
        realesrgan_system = shutil.which("inference_realesrgan_video.py")
        if realesrgan_system:
            return Path(realesrgan_system)
        # Fallback: Lokaler Pfad
        return self.base_dir / "dv2plex" / "bin" / "realesrgan" / "inference_realesrgan_video.py"
    
    def get_dv_import_root(self) -> Path:
        """Gibt den Root-Pfad für DV-Importe zurück"""
        path = self.get("paths.dv_import_root")
        if path:
            p = Path(path)
            # Ensure absolute path
            if not p.is_absolute():
                p = p.resolve()
            return p
        result = self.base_dir / "dv2plex" / "DV_Import"
        # Ensure absolute path
        if not result.is_absolute():
            result = result.resolve()
        return result
    
    def get_plex_movies_root(self) -> Path:
        """Gibt den Root-Pfad für Plex-Movies zurück"""
        path = self.get("paths.plex_movies_root")
        if path:
            # Expandiere ~ zu vollständigem Pfad
            return Path(path).expanduser()
        # Linux Standard: ~/Plex/Movies
        return Path.home() / "Plex" / "Movies"
    
    def get_device_name(self) -> str:
        """Gibt den FireWire-Gerätepfad zurück (für Kompatibilität)"""
        return self.get_firewire_device()
    
    def get_firewire_device(self) -> Optional[str]:
        """Gibt den FireWire-Gerätepfad zurück"""
        device = self.get("device.firewire_device", "")
        if device and device.strip():
            return device
        # Leer = Auto-Detection
        return None
    
    def set_firewire_device(self, device: str):
        """Setzt den FireWire-Gerätepfad"""
        self.set("device.firewire_device", device)
        self.save_config()
    
    def set_device_name(self, name: str):
        """Setzt den FireWire-Gerätepfad (für Kompatibilität)"""
        self.set_firewire_device(name)
    
    def get_upscaling_profile(self, profile_name: Optional[str] = None) -> Dict[str, Any]:
        """Gibt ein Upscaling-Profil zurück"""
        if profile_name is None:
            profile_name = self.get("upscaling.default_profile", "realesrgan_4x_hq")
        
        profiles = self.get("upscaling.profiles", {})
        return profiles.get(profile_name, {})
    
    def get_log_directory(self) -> Path:
        """Gibt das Log-Verzeichnis zurück"""
        log_dir = self.get("logging.log_directory")
        if log_dir:
            return Path(log_dir)
        return self.base_dir / "dv2plex" / "logs"

