"""
Konfigurations-Management für DV2Plex
"""

import json
import os
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
        
        return {
            "version": "1.0",
            "paths": {
                "plex_movies_root": str(dv2plex_dir / "PlexMovies"),
                "dv_import_root": str(dv2plex_dir / "DV_Import"),
                "ffmpeg_path": str(dv2plex_dir / "bin" / "ffmpeg.exe"),
                "realesrgan_path": str(dv2plex_dir / "bin" / "realesrgan" / "inference_realesrgan_video.py")
            },
            "device": {
                "dshow_video_device": ""
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
                "auto_postprocess": False
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
                return merged
            except Exception as e:
                print(f"Fehler beim Laden der Konfiguration: {e}")
                return self.default_config.copy()
        else:
            # Erstelle Standard-Konfiguration
            self.save_config(self.default_config)
            return self.default_config.copy()
    
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
        path = self.get("paths.ffmpeg_path")
        if path:
            return Path(path)
        return self.base_dir / "dv2plex" / "bin" / "ffmpeg.exe"
    
    def get_realesrgan_path(self) -> Path:
        """Gibt den Pfad zu inference_realesrgan_video.py zurück"""
        path = self.get("paths.realesrgan_path")
        if path:
            return Path(path)
        return self.base_dir / "dv2plex" / "bin" / "realesrgan" / "inference_realesrgan_video.py"
    
    def get_dv_import_root(self) -> Path:
        """Gibt den Root-Pfad für DV-Importe zurück"""
        path = self.get("paths.dv_import_root")
        if path:
            return Path(path)
        return self.base_dir / "dv2plex" / "DV_Import"
    
    def get_plex_movies_root(self) -> Path:
        """Gibt den Root-Pfad für Plex-Movies zurück"""
        path = self.get("paths.plex_movies_root")
        if path:
            return Path(path)
        return self.base_dir / "dv2plex" / "PlexMovies"
    
    def get_device_name(self) -> str:
        """Gibt den DirectShow-Device-Namen zurück"""
        return self.get("device.dshow_video_device", "")
    
    def set_device_name(self, name: str):
        """Setzt den DirectShow-Device-Namen"""
        self.set("device.dshow_video_device", name)
        self.save_config()
    
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

