"""
Upscale-Engine für Real-ESRGAN Video-Integration
"""

import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional, Callable
import logging


class UpscaleEngine:
    """Verwaltet Video-Upscaling mit Real-ESRGAN Video-Skript"""
    
    def __init__(self, realesrgan_path: Path, ffmpeg_path: Optional[Path] = None, log_callback: Optional[Callable] = None):
        """
        Initialisiert die Upscale-Engine
        
        Args:
            realesrgan_path: Pfad zu inference_realesrgan_video.py
            ffmpeg_path: Pfad zu ffmpeg (wird vom Skript benötigt)
            log_callback: Optionaler Callback für Log-Nachrichten
        """
        self.realesrgan_path = realesrgan_path
        self.ffmpeg_path = ffmpeg_path
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)
        self.process: Optional[subprocess.Popen] = None
    
    def upscale(
        self,
        input_path: Path,
        output_path: Path,
        profile: Dict[str, Any],
        progress_hook: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """
        Führt Video-Upscaling mit Real-ESRGAN Video-Skript durch (direkt Video-zu-Video)
        
        Args:
            input_path: Pfad zur Eingabedatei (movie_merged.avi)
            output_path: Pfad zur Ausgabedatei (4K-Video)
            profile: Upscaling-Profil (aus Config)
        
        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        if not input_path.exists():
            self.log(f"Eingabedatei nicht gefunden: {input_path}")
            return False
        
        # Erstelle Ausgabeordner
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        backend = profile.get("backend", "realesrgan")
        
        # Prüfe ob ffmpeg-only Backend
        if backend == "ffmpeg":
            return self._ffmpeg_only_upscale(input_path, output_path, profile)
        
        # Real-ESRGAN Backend
        if not self.realesrgan_path.exists():
            self.log(f"Real-ESRGAN nicht gefunden: {self.realesrgan_path}")
            return False
        
        # Real-ESRGAN Video-Skript erstellt Output in results/ Ordner
        # Wir verwenden einen temporären Output-Ordner
        import tempfile
        temp_output_dir = Path(tempfile.mkdtemp(prefix="realesrgan_video_"))
        
        try:
            self.log(f"Starte Upscaling: {input_path.name} -> {output_path.name}")
            self.log(f"Profil: {profile.get('backend', 'unknown')}")
            
            # Optimierte Strategie: Real-ESRGAN 2x, dann ffmpeg auf 4K
            # Das ist deutlich schneller bei minimalem Qualitätsverlust
            model_name = profile.get("model", "RealESRGAN_x4plus")
            target_scale = profile.get("scale_factor", 4)
            
            # Verwende 2x für Real-ESRGAN (schneller)
            realesrgan_scale = 2
            tile_size = profile.get("tile_size", 400)  # 400 für bessere Performance
            tile_pad = profile.get("tile_pad", 10)
            
            cmd = [
                sys.executable,
                str(self.realesrgan_path),
                "-i", str(input_path),
                "-n", model_name,
                "-s", str(realesrgan_scale),  # Immer 2x für Real-ESRGAN
                "-o", str(temp_output_dir),
                "--tile", str(tile_size),
                "--tile_pad", str(tile_pad),
                "--num_process_per_gpu", "1"
            ]
            
            # Füge ffmpeg-Pfad hinzu falls vorhanden
            if self.ffmpeg_path and self.ffmpeg_path.exists():
                cmd.extend(["--ffmpeg_bin", str(self.ffmpeg_path)])
            
            self.log(f"Real-ESRGAN Video-Befehl: {' '.join(cmd)}")
            
            # Starte Prozess
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self.realesrgan_path.parent),
                bufsize=1
            )
            
            # Zeige Fortschritt (stderr enthält Progress-Info)
            import time
            last_log_time = time.time()
            
            while True:
                returncode = self.process.poll()
                if returncode is not None:
                    break
                
                # Lese stderr für Fortschrittsanzeige
                try:
                    line = self.process.stderr.readline()
                    if line:
                        line = line.strip()
                        if line and ("%" in line or "frame" in line.lower() or "fps" in line.lower()):
                            # Zeige Fortschritt alle 2 Sekunden
                            current_time = time.time()
                            if current_time - last_log_time >= 2.0:
                                self.log(f"Real-ESRGAN: {line}")
                                last_log_time = current_time
                except:
                    pass
                
                time.sleep(0.1)
            
            # Warte auf vollständige Beendigung
            stdout, stderr = self.process.communicate()
            
            if returncode != 0:
                self.log(f"Real-ESRGAN-Fehler (Code {returncode})")
                if stderr:
                    self.log(f"stderr: {stderr[-2000:]}")
                if stdout:
                    self.log(f"stdout: {stdout[-1000:]}")
                return False
            
            # Finde Output-Datei (Skript erstellt: input_name_out.mp4)
            input_stem = input_path.stem
            realesrgan_output = temp_output_dir / f"{input_stem}_out.mp4"
            
            if not realesrgan_output.exists():
                # Versuche alle .mp4 Dateien im Output-Ordner
                mp4_files = list(temp_output_dir.glob("*.mp4"))
                if mp4_files:
                    realesrgan_output = mp4_files[0]
                    self.log(f"Gefundene Real-ESRGAN Output-Datei: {realesrgan_output.name}")
                else:
                    self.log(f"Real-ESRGAN Output-Datei nicht gefunden in {temp_output_dir}")
                    self.log(f"Verfügbare Dateien: {list(temp_output_dir.iterdir())}")
                    return False
            
            self.log(f"Real-ESRGAN 2x abgeschlossen: {realesrgan_output}")
            
            # Schritt 2: ffmpeg auf 4K hochskalieren (wenn target_scale > 2)
            target_scale = profile.get("scale_factor", 4)
            if target_scale > 2:
                self.log(f"Skaliere mit ffmpeg auf {target_scale}x (4K)...")
                if not self._ffmpeg_upscale_to_4k(realesrgan_output, output_path, profile, progress_hook):
                    return False
            else:
                # Wenn target_scale <= 2, kopiere einfach die Real-ESRGAN Ausgabe
                import shutil
                shutil.copy2(realesrgan_output, output_path)
                self.log(f"Video erfolgreich erstellt: {output_path}")
            
            return True
            
        except Exception as e:
            self.log(f"Fehler beim Upscaling: {e}")
            import traceback
            self.log(traceback.format_exc())
            return False
        finally:
            # Aufräumen: Lösche temporären Ordner
            try:
                import shutil
                shutil.rmtree(temp_output_dir)
            except:
                pass
    
    def _ffmpeg_only_upscale(self, input_video: Path, output_path: Path, profile: Dict[str, Any], progress_hook: Optional[Callable[[int], None]] = None) -> bool:
        """Nur ffmpeg Upscaling (schnell, keine AI) - einfacher Ansatz"""
        if not self.ffmpeg_path or not self.ffmpeg_path.exists():
            self.log("ffmpeg nicht gefunden")
            return False
        
        scale_factor = profile.get("scale_factor", 4)
        encoder_options = profile.get("encoder_options", {})
        
        # Bestimme Ziel-Auflösung basierend auf scale_factor
        if scale_factor == 4:
            scale_filter = "scale=3840:2160:flags=lanczos"
        elif scale_factor == 2:
            scale_filter = "scale=1920:1080:flags=lanczos"
        else:
            scale_filter = f"scale=iw*{scale_factor}:ih*{scale_factor}:flags=lanczos"
        
        # Einfacher Befehl wie gewünscht
        cmd = [
            str(self.ffmpeg_path),
            "-i", str(input_video),
            "-vf", scale_filter,
            "-c:v", "libx264",
            "-preset", encoder_options.get("preset", "veryfast"),
            "-crf", str(encoder_options.get("crf", 18)),
            "-c:a", "copy",
            "-y", str(output_path)
        ]
        
        try:
            self.log(f"ffmpeg-only Upscaling ({scale_factor}x): {' '.join(cmd)}")
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # Zeige Fortschritt
            import time
            last_log_time = time.time()
            stderr_lines = []
            last_progress = 0
            
            while True:
                returncode = self.process.poll()
                if returncode is not None:
                    break
                
                try:
                    line = self.process.stderr.readline()
                    if line:
                        line = line.strip()
                        stderr_lines.append(line)
                        if line.startswith("frame=") or ("fps=" in line and "size=" in line):
                            current_time = time.time()
                            if current_time - last_log_time >= 2.0:
                                self.log(f"ffmpeg: {line[:100]}")
                                last_log_time = current_time
                            if progress_hook:
                                try:
                                    if "frame=" in line:
                                        parts = line.split()
                                        for p in parts:
                                            if p.startswith("frame="):
                                                frame_val = int(p.split("=")[1])
                                                est = min(100, max(last_progress, int(frame_val / 3000 * 100)))
                                                last_progress = est
                                                progress_hook(est)
                                                break
                                except Exception:
                                    pass
                except:
                    pass
                
                time.sleep(0.1)
            
            # Warte auf vollständige Beendigung
            stdout, stderr = self.process.communicate()
            
            # Kombiniere alle stderr-Lines
            full_stderr = "\n".join(stderr_lines)
            if stderr:
                full_stderr += "\n" + stderr
            
            if returncode != 0:
                # Zeige nur relevante Fehler (ohne "Concealing bitstream errors")
                error_lines = [l for l in full_stderr.split("\n") if l and "Concealing" not in l and "repeated" not in l and "AC EOB" not in l]
                error_msg = "\n".join(error_lines[-20:])
                self.log(f"ffmpeg Upscaling Fehler (Code {returncode}): {error_msg}")
                return False
            
            if output_path.exists():
                self.log(f"Video erfolgreich erstellt: {output_path}")
                return True
            else:
                self.log("Video-Datei wurde nicht erstellt")
                return False
                
        except Exception as e:
            self.log(f"Fehler beim ffmpeg Upscaling: {e}")
            return False
    
    def _ffmpeg_upscale_to_4k(self, input_video: Path, output_path: Path, profile: Dict[str, Any], progress_hook: Optional[Callable[[int], None]] = None) -> bool:
        """Skaliert Video mit ffmpeg schnell auf 4K hoch (Lanczos)"""
        if not self.ffmpeg_path or not self.ffmpeg_path.exists():
            self.log("ffmpeg nicht gefunden für 4K-Upscaling")
            return False
        
        encoder = profile.get("encoder", "libx264")
        encoder_options = profile.get("encoder_options", {})
        
        # ffmpeg-Befehl für schnelles 4K-Upscaling
        cmd = [
            str(self.ffmpeg_path),
            "-i", str(input_video),
            "-vf", "scale=3840:2160:flags=lanczos",  # 4K mit Lanczos
            "-c:v", encoder,
            "-preset", "veryfast",  # Schnell
            "-crf", str(encoder_options.get("crf", 18)),  # Qualität aus Profil
            "-c:a", "copy"  # Audio kopieren
        ]
        
        # Weitere Encoder-Optionen (außer crf, preset die wir schon haben)
        skip_options = {"crf", "preset"}
        for key, value in encoder_options.items():
            if key not in skip_options:
                cmd.extend(["-" + key, str(value)])
        
        cmd.extend(["-y", str(output_path)])
        
        try:
            self.log(f"ffmpeg 4K-Upscaling: {' '.join(cmd)}")
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            import time
            last_log_time = time.time()
            last_progress = 0
            stderr_lines = []

            while True:
                returncode = self.process.poll()
                if returncode is not None:
                    break

                try:
                    line = self.process.stderr.readline()
                    if line:
                        line = line.strip()
                        stderr_lines.append(line)
                        if line.startswith("frame=") or ("fps=" in line and "size=" in line):
                            current_time = time.time()
                            if current_time - last_log_time >= 2.0:
                                self.log(f"ffmpeg: {line[:100]}")
                                last_log_time = current_time
                            if progress_hook:
                                try:
                                    if "frame=" in line:
                                        parts = line.split()
                                        for p in parts:
                                            if p.startswith("frame="):
                                                frame_val = int(p.split("=")[1])
                                                est = min(100, max(last_progress, int(frame_val / 4000 * 100)))
                                                last_progress = est
                                                progress_hook(est)
                                                break
                                except Exception:
                                    pass
                except:
                    pass

                time.sleep(0.1)

            stdout, stderr = self.process.communicate()
            
            if self.process.returncode != 0:
                self.log(f"ffmpeg 4K-Upscaling Fehler: {stderr[-1000:]}")
                return False
            
            if output_path.exists():
                self.log(f"4K-Video erfolgreich erstellt: {output_path}")
                return True
            else:
                self.log("4K-Video-Datei wurde nicht erstellt")
                return False
                
        except Exception as e:
            self.log(f"Fehler beim 4K-Upscaling: {e}")
            return False
    
    def is_running(self) -> bool:
        """Prüft ob Upscaling läuft"""
        if self.process is None:
            return False
        return self.process.poll() is None
    
    def stop(self):
        """Stoppt laufendes Upscaling (falls möglich)"""
        if self.process and self.is_running():
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except:
                self.process.kill()
    
    def log(self, message: str):
        """Loggt eine Nachricht"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)

