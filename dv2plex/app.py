"""
Hauptprogramm für DV2Plex - GUI und Workflow-Orchestrierung
"""

import sys
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Callable
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QFileDialog,
    QMessageBox,
    QComboBox,
    QProgressBar,
    QTabWidget,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QSplitter,
    QFrame,
    QGraphicsDropShadowEffect,
    QSizePolicy,
    QToolButton,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QScrollArea,
    QSpinBox
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QObject, QPoint, QSize, QEvent, QRect
from PySide6.QtGui import QImage, QPixmap, QColor, QPainter, QPainterPath, QPen, QBrush, QMouseEvent, QLinearGradient

import re

# Imports - unterstützt sowohl Modul- als auch direkte Ausführung
try:
    from .config import Config
    from .capture import CaptureEngine
    from .merge import MergeEngine
    from .upscale import UpscaleEngine
    from .plex_export import PlexExporter
    from .frame_extraction import FrameExtractionEngine
    from .cover_generation import CoverGenerationEngine
except ImportError:
    # Fallback für direkte Ausführung
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from dv2plex.config import Config
    from dv2plex.capture import CaptureEngine
    from dv2plex.merge import MergeEngine
    from dv2plex.upscale import UpscaleEngine
    from dv2plex.plex_export import PlexExporter
    from dv2plex.frame_extraction import FrameExtractionEngine
    from dv2plex.cover_generation import CoverGenerationEngine


class PreviewBridge(QObject):
    frame_ready = Signal(QImage)


LIQUID_STYLESHEET = """
/* Liquid Glass Theme - Enhanced v2 */
QWidget {
    font-family: 'Segoe UI', sans-serif;
    font-size: 14px;
    font-weight: 600; /* Global etwas dickere Schrift */
    color: #e0e6f6;
}

/* Transparenter Hintergrund für das Hauptfenster */
QMainWindow {
    background: transparent;
}

/* Style für die Tabs - Schwebend & Abgerundet */
QTabWidget::pane {
    border: none;
    background: transparent;
}

QTabWidget::tab-bar {
    left: 20px;
}

QTabBar::tab {
    background-color: rgba(60, 60, 80, 0.4);
    color: #a0a0b0;
    padding: 10px 24px;
    margin-right: 12px;
    margin-bottom: 8px; /* Abstand zum Pane -> Schwebend */
    border-radius: 20px; /* Pillen-Form / Komplett abgerundet */
    border: 1px solid rgba(255, 255, 255, 0.05);
    font-weight: 700; /* Tabs noch etwas fetter */
    min-width: 100px;
    alignment: center;
}

QTabBar::tab:selected {
    background-color: rgba(0, 210, 255, 0.25); /* Cyan Glass Accent */
    color: #ffffff;
    border: 1px solid rgba(0, 210, 255, 0.8);
    box-shadow: 0px 0px 10px rgba(0, 210, 255, 0.3);
}

QTabBar::tab:hover:!selected {
    background-color: rgba(255, 255, 255, 0.15);
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.2);
}

/* Inputs & Lists */
QLineEdit, QTextEdit, QListWidget {
    background-color: rgba(10, 10, 15, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #ffffff;
    border-radius: 12px;
    padding: 10px;
    selection-background-color: rgba(0, 210, 255, 0.5);
    selection-color: #ffffff;
    font-weight: 500;
}

QLineEdit:focus, QTextEdit:focus, QListWidget:focus {
    border: 1px solid rgba(0, 210, 255, 0.8); /* Cyan focus */
    background-color: rgba(20, 20, 30, 0.7);
}

/* ComboBox */
QComboBox {
    background-color: rgba(10, 10, 15, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 10px 15px;
    color: #ffffff;
    font-weight: 500;
}

QComboBox:hover {
    border: 1px solid rgba(0, 210, 255, 0.6);
    background-color: rgba(20, 20, 30, 0.6);
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 30px;
    border-left-width: 0px;
    border-top-right-radius: 12px;
    border-bottom-right-radius: 12px;
}

QComboBox::down-arrow {
    width: 0; 
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #a0a0b0;
    margin-right: 10px;
}

QComboBox::down-arrow:on {
    border-top: 6px solid #00d2ff;
}

QComboBox QAbstractItemView {
    border: 1px solid rgba(0, 210, 255, 0.3);
    background-color: #1e1e28;
    border-radius: 12px;
    selection-background-color: rgba(0, 210, 255, 0.2);
    color: #ffffff;
    outline: none;
    padding: 5px;
}

QComboBox QAbstractItemView::item {
    padding: 8px;
    border-radius: 6px;
}

QComboBox QAbstractItemView::item:hover {
    background-color: rgba(255, 255, 255, 0.1);
}

QComboBox QAbstractItemView::item:selected {
    background-color: rgba(0, 210, 255, 0.2);
    color: #ffffff;
}

/* Buttons */
QPushButton {
    background-color: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 12px 24px;
    color: #ffffff;
    font-weight: 700; /* Button Text fett */
    font-size: 14px;
}

QPushButton:hover {
    background-color: rgba(0, 210, 255, 0.2);
    border: 1px solid rgba(0, 210, 255, 0.6);
    color: #ffffff;
}

QPushButton:pressed {
    background-color: rgba(0, 210, 255, 0.4);
}

QPushButton:disabled {
    background-color: rgba(30, 30, 30, 0.3);
    color: #606070;
    border: 1px solid rgba(255, 255, 255, 0.02);
}

/* Labels */
QLabel#previewLabel {
    background-color: rgba(0, 0, 0, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 12px;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: rgba(0, 0, 0, 0.1);
    width: 8px;
    border-radius: 4px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.2);
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(0, 210, 255, 0.5);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Checkbox */
QCheckBox {
    spacing: 8px;
    color: #e0e6f6;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid rgba(255, 255, 255, 0.3);
    background: rgba(0, 0, 0, 0.3);
}
QCheckBox::indicator:checked {
    background-color: rgba(0, 210, 255, 0.8);
    border-color: rgba(0, 210, 255, 1.0);
}

/* ProgressBar */
QProgressBar {
    background-color: rgba(0, 0, 0, 0.4);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    text-align: center;
    color: #ffffff;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(0, 180, 219, 0.9), stop:1 rgba(0, 131, 176, 0.9));
    border-radius: 6px;
}

/* Splitter */
QSplitter::handle {
    background-color: rgba(255, 255, 255, 0.1);
    width: 2px;
}

/* GroupBox */
QGroupBox {
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 12px;
    margin-top: 12px;
    padding-top: 12px;
    background-color: rgba(20, 20, 30, 0.3);
    font-weight: 700;
    color: #e0e6f6;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #00d2ff;
}

/* SpinBox */
QSpinBox {
    background-color: rgba(10, 10, 15, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 8px 12px;
    color: #ffffff;
    font-weight: 500;
    min-width: 80px;
}

QSpinBox:hover {
    border: 1px solid rgba(0, 210, 255, 0.6);
    background-color: rgba(20, 20, 30, 0.6);
}

QSpinBox:focus {
    border: 1px solid rgba(0, 210, 255, 0.8);
    background-color: rgba(20, 20, 30, 0.7);
}

QSpinBox::up-button, QSpinBox::down-button {
    background-color: rgba(0, 210, 255, 0.2);
    border: none;
    border-radius: 6px;
    width: 20px;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: rgba(0, 210, 255, 0.4);
}

QSpinBox::up-arrow, QSpinBox::down-arrow {
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
}

QSpinBox::up-arrow {
    border-bottom: 5px solid #a0a0b0;
}

QSpinBox::down-arrow {
    border-top: 5px solid #a0a0b0;
}

/* Dialog */
QDialog {
    background: transparent;
}

/* DialogButtonBox */
QDialogButtonBox {
    background: transparent;
}

QDialogButtonBox QPushButton {
    min-width: 100px;
}
"""

class ModernTitleBar(QWidget):
    """Custom Title Bar für das Liquid Design"""
    def __init__(self, parent=None, title="DV2Plex"):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(40)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)
        layout.setSpacing(10)
        
        # Titel
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: bold; color: #e0e6f6; font-size: 14px; background: transparent;")
        layout.addWidget(self.title_label)
        
        layout.addStretch()
        
        # Window Controls
        btn_style = """
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 10px;
                color: #e0e6f6;
                font-weight: bold;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 0.1);
            }
        """
        close_style = """
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 10px;
                color: #e0e6f6;
                font-weight: bold;
            }
            QToolButton:hover {
                background: rgba(255, 80, 80, 0.8);
            }
        """
        
        # Settings Button
        self.btn_settings = QToolButton()
        self.btn_settings.setText("⚙")
        self.btn_settings.setFixedSize(30, 30)
        self.btn_settings.setStyleSheet(btn_style)
        self.btn_settings.setToolTip("Einstellungen")
        layout.addWidget(self.btn_settings)
        
        self.btn_min = QToolButton()
        self.btn_min.setText("—")
        self.btn_min.setFixedSize(30, 30)
        self.btn_min.setStyleSheet(btn_style)
        self.btn_min.clicked.connect(self.minimize_window)
        
        self.btn_max = QToolButton()
        self.btn_max.setText("☐")
        self.btn_max.setFixedSize(30, 30)
        self.btn_max.setStyleSheet(btn_style)
        self.btn_max.clicked.connect(self.maximize_restore_window)
        
        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setFixedSize(30, 30)
        self.btn_close.setStyleSheet(close_style)
        self.btn_close.clicked.connect(self.close_window)
        
        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)
        
        self.start_pos = None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.start_pos and self.parent_window:
            delta = event.globalPosition().toPoint() - self.start_pos
            self.parent_window.move(self.parent_window.pos() + delta)
            self.start_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.start_pos = None

    def minimize_window(self):
        if self.parent_window:
            self.parent_window.showMinimized()

    def maximize_restore_window(self):
        if self.parent_window:
            if self.parent_window.isMaximized():
                self.parent_window.showNormal()
            else:
                self.parent_window.showMaximized()

    def close_window(self):
        if self.parent_window:
            self.parent_window.close()


class LiquidContainer(QFrame):
    """Haupt-Container mit abgerundeten Ecken und halbtransparentem Hintergrund"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        radius = 20
        
        # Pfad für abgerundetes Rechteck
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        
        # 1. Gradient Background (Liquid Deep Blue/Purple)
        # Verlauf von tiefem Dunkelblau zu etwas hellerem Grau-Blau
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(15, 15, 25, 230))    # Deep Dark
        gradient.setColorAt(1.0, QColor(35, 40, 60, 220))    # Lighter Blue-ish
        painter.setBrush(QBrush(gradient))
        
        # 2. Rand (Subtil leuchtend)
        pen = QPen(QColor(255, 255, 255, 20), 1)
        painter.setPen(pen)
        painter.drawPath(path)
        
        # 3. Glossy Overlay (Lichtreflexion oben)
        # Erzeugt den "Glas"-Effekt durch einen weißen Verlauf im oberen Bereich
        painter.setPen(Qt.NoPen)
        gloss_gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gloss_gradient.setColorAt(0.0, QColor(255, 255, 255, 15))
        gloss_gradient.setColorAt(0.2, QColor(255, 255, 255, 5))
        gloss_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        
        gloss_path = QPainterPath()
        gloss_rect = QRect(0, 0, rect.width(), int(rect.height() * 0.4))
        gloss_path.addRoundedRect(gloss_rect, radius, radius)
        
        # Wir schneiden den unteren Teil des Gloss-Rechtecks nicht ab, sondern nutzen den Gradient,
        # der transparent wird. Aber wir müssen sicherstellen, dass er nicht über die Ecken malt.
        # Einfachste Methode: Den gleichen Path wie background nutzen aber mit Gradient füllen
        painter.setBrush(QBrush(gloss_gradient))
        painter.drawPath(path)



class PipeReaderThread(QThread):
    """Hintergrund-Thread zum Auslesen von Prozess-Pipes (z.B. stderr)."""
    def __init__(self, pipe, callback=None):
        super().__init__()
        self.pipe = pipe
        self.callback = callback
        self._running = True

    def run(self):
        try:
            while self._running:
                line = self.pipe.readline()
                if not line:
                    break
                if self.callback:
                    try:
                        self.callback(line.decode("utf-8", errors="ignore"))
                    except Exception:
                        pass
        except Exception:
            pass

    def stop(self):
        self._running = False


class PostprocessingThread(QThread):
    """Thread für Postprocessing im Hintergrund"""
    progress = Signal(int)
    status = Signal(str)
    log_message = Signal(str)
    finished = Signal(bool, str)  # success, message
    
    def __init__(self, config: Config, movie_dir: Path, profile_name: str):
        super().__init__()
        self.config = config
        self.movie_dir = movie_dir
        self.profile_name = profile_name
        self._stop_requested = False
    
    def run(self):
        """Führt Postprocessing aus"""
        try:
            title, year = self._parse_movie_folder_name(self.movie_dir.name)
            movie_name = self.movie_dir.name
            title = title or movie_name
            display_name = f"{title} ({year})" if year else movie_name
            
            self.status.emit(f"Postprocessing: {display_name}")
            self.progress.emit(0)
            
            # Merge
            self.log_message.emit(f"=== Starte Merge: {display_name} ===")
            lowres_dir = self.movie_dir / "LowRes"
            merge_engine = MergeEngine(
                self.config.get_ffmpeg_path(),
                log_callback=lambda msg: self.log_message.emit(msg)
            )
            merged_file = merge_engine.merge_parts(lowres_dir)
            
            if not merged_file or not merged_file.exists():
                self.finished.emit(False, f"Merge fehlgeschlagen für {display_name}!")
                return
            
            self.progress.emit(20)
            
            # Timestamp-Overlay (falls aktiviert)
            timestamp_overlay = self.config.get("capture.timestamp_overlay", True)
            if timestamp_overlay:
                self.log_message.emit("=== Füge Timestamp-Overlays hinzu ===")
                timestamp_duration = self.config.get("capture.timestamp_duration", 4)
                
                # Erstelle temporäre Datei mit Timestamps
                temp_merged = merged_file.parent / f"{merged_file.stem}_with_timestamps{merged_file.suffix}"
                result_file = merge_engine.add_timestamp_overlay(
                    merged_file,
                    temp_merged,
                    duration=timestamp_duration
                )
                
                if result_file and result_file.exists():
                    # Ersetze merged_file mit Version mit Timestamps
                    merged_file.unlink()
                    result_file.rename(merged_file)
                    self.log_message.emit("Timestamp-Overlays erfolgreich hinzugefügt")
                else:
                    self.log_message.emit("Warnung: Timestamp-Overlay fehlgeschlagen, verwende Datei ohne Timestamps")
            
            self.progress.emit(25)
            
            # Upscale
            auto_upscale = self.config.get("capture.auto_upscale", True)
            if auto_upscale:
                self.log_message.emit("=== Starte Upscaling ===")
                highres_dir = self.movie_dir / "HighRes"
                highres_dir.mkdir(parents=True, exist_ok=True)
                
                profile = self.config.get_upscaling_profile(self.profile_name)
                output_file = highres_dir / f"{movie_name}_4k.mp4"
                
                upscale_engine = UpscaleEngine(
                    self.config.get_realesrgan_path(),
                    ffmpeg_path=self.config.get_ffmpeg_path(),
                    log_callback=lambda msg: self.log_message.emit(msg)
                )
                
                if upscale_engine.upscale(merged_file, output_file, profile):
                    self.progress.emit(75)
                    
                    # Export
                    auto_export = self.config.get("capture.auto_export", False)
                    if auto_export:
                        self.log_message.emit("=== Starte Plex-Export ===")
                        plex_exporter = PlexExporter(
                            self.config.get_plex_movies_root(),
                            log_callback=lambda msg: self.log_message.emit(msg)
                        )
                        
                        result = plex_exporter.export_movie(
                            output_file,
                            title,
                            year or ""
                        )
                        
                        if result:
                            self.progress.emit(100)
                            self.finished.emit(True, f"Film erfolgreich verarbeitet und nach Plex exportiert:\n{result}")
                        else:
                            self.finished.emit(True, f"Postprocessing abgeschlossen (Export fehlgeschlagen)")
                    else:
                        self.progress.emit(100)
                        self.finished.emit(True, f"Film erfolgreich verarbeitet:\n{output_file}")
                else:
                    self.finished.emit(False, "Upscaling fehlgeschlagen!")
                    return
            else:
                self.progress.emit(100)
                self.finished.emit(True, "Merge abgeschlossen (Upscaling übersprungen)")
            
        except Exception as e:
            self.finished.emit(False, f"Fehler beim Postprocessing: {e}")
    
    def _parse_movie_folder_name(self, folder_name: str) -> tuple[str, str]:
        """Extrahiert Titel und Jahr aus Ordnernamen"""
        match = re.match(r"^(.+?)\s*\((\d{4})\)$", folder_name)
        if match:
            return match.group(1).strip(), match.group(2)
        return folder_name, ""


class PreviewThread(QThread):
    """Thread für Live-Preview der Kamera - vereinfachte Version"""
    frame_ready = Signal(QImage)
    error_occurred = Signal(str)
    
    def __init__(self, ffmpeg_path: Path, device_name: str, fps: int = 5):
        super().__init__()
        self.ffmpeg_path = ffmpeg_path
        self.device_name = device_name
        self.fps = fps
        self.running = False
        self.process = None
    
    def run(self):
        """Startet den Preview-Stream"""
        import subprocess
        import time
        
        # Linux: Verwende dv1394 statt dshow
        cmd = [
            str(self.ffmpeg_path),
            "-f", "dv1394",
            "-i", self.device_name,  # device_name ist jetzt der Gerätepfad (z.B. /dev/raw1394)
            "-vf", f"fps={self.fps},scale=640:-1",
            "-f", "mjpeg",
            "-q:v", "5",
            "-"
        ]
        
        try:
            self.running = True
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            # Starte Thread zum Auslesen von stderr, damit der Puffer nicht blockiert
            self.stderr_output = []

            def stderr_logger(line: str):
                line = line.strip()
                if line:
                    self.stderr_output.append(line)

            self.stderr_thread = PipeReaderThread(self.process.stderr, stderr_logger)
            self.stderr_thread.start()

            buffer = bytearray()
            jpeg_start = b'\xff\xd8'
            jpeg_end = b'\xff\xd9'
            frame_time = 1.0 / self.fps
            last_frame_time = 0
            
            while self.running:
                if self.process.poll() is not None:
                    # Prozess beendet - prüfe gesammelte stderr-Ausgabe für Fehler
                    stderr_text = "\n".join(self.stderr_output[-5:])
                    if stderr_text:
                        lower = stderr_text.lower()
                        if "error" in lower or "failed" in lower:
                            self.error_occurred.emit(f"ffmpeg Fehler: {stderr_text[:200]}")
                    break
                
                try:
                    # Lese Daten in kleineren Chunks für bessere Responsiveness
                    chunk = self.process.stdout.read(4096)
                    if not chunk:
                        # Keine Daten - kurze Pause
                        time.sleep(0.02)
                        continue
                    
                    buffer.extend(chunk)
                    
                    # Suche nach vollständigen JPEGs - verarbeite alle gefundenen Frames
                    frames_found = []
                    while True:
                        start_idx = buffer.find(jpeg_start)
                        if start_idx == -1:
                            # Kein JPEG-Start gefunden
                            if len(buffer) > 200000:
                                # Buffer zu groß - zurücksetzen
                                buffer = bytearray()
                            break
                        
                        # Entferne Daten vor JPEG-Start
                        if start_idx > 0:
                            buffer = buffer[start_idx:]
                        
                        # Suche nach JPEG-Ende
                        end_idx = buffer.find(jpeg_end, 2)
                        if end_idx == -1:
                            # Noch kein vollständiges JPEG
                            break
                        
                        # Extrahiere JPEG
                        jpeg_data = bytes(buffer[:end_idx + 2])
                        buffer = buffer[end_idx + 2:]
                        frames_found.append(jpeg_data)
                    
                    # Zeige das neueste Frame (mit Rate-Limiting)
                    if frames_found:
                        current_time = time.time()
                        # Lockere Rate-Limiting: erlaube Frame wenn genug Zeit vergangen ist
                        # oder wenn es das erste Frame ist
                        if last_frame_time == 0 or (current_time - last_frame_time >= frame_time):
                            # Nimm das letzte (neueste) Frame
                            jpeg_data = frames_found[-1]
                            try:
                                image = QImage.fromData(jpeg_data)
                                if not image.isNull():
                                    self.frame_ready.emit(image)
                                    last_frame_time = current_time
                            except Exception as e:
                                # Fehler beim Dekodieren - überspringe Frame
                                pass
                        
                except Exception as e:
                    if self.running:
                        self.error_occurred.emit(f"Fehler: {str(e)}")
                    # Nicht abbrechen, sondern weiter versuchen
                    time.sleep(0.1)
                    continue
            
        except Exception as e:
            self.error_occurred.emit(f"Preview-Fehler: {str(e)}")
        finally:
            self.running = False
            if self.process:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except:
                    try:
                        self.process.kill()
                    except:
                        pass
    
    def stop(self):
        """Stoppt den Preview"""
        self.running = False
        if hasattr(self, "stderr_thread") and self.stderr_thread:
            self.stderr_thread.stop()
            self.stderr_thread.wait(500)
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                try:
                    self.process.kill()
                except:
                    pass


class MainWindow(QMainWindow):
    """Hauptfenster der Anwendung"""
    
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.setup_logging()
        
        self.preview_bridge = PreviewBridge()
        self.preview_bridge.frame_ready.connect(self.update_preview)
        
        # Engines
        self.capture_engine: Optional[CaptureEngine] = None
        self.merge_engine: Optional[MergeEngine] = None
        self.upscale_engine: Optional[UpscaleEngine] = None
        self.plex_exporter: Optional[PlexExporter] = None
        
        # Preview
        self.preview_thread: Optional[PreviewThread] = None
        self.capture_preview_active = False
        
        # Workflow-State
        self.current_movie_title = ""
        self.current_year = ""
        self.current_movie_dir: Optional[Path] = None
        self.part_number = 1
        self.preview_was_running_before_capture = False
        
        # UI references
        self.tabs: Optional[QTabWidget] = None
        self.capture_tab: Optional[QWidget] = None
        self.postprocess_tab: Optional[QWidget] = None
        self.movie_mode_tab: Optional[QWidget] = None
        self.cover_tab: Optional[QWidget] = None
        self.postprocess_list: Optional[QListWidget] = None
        self.movie_mode_list: Optional[QListWidget] = None
        self.cover_video_list: Optional[QListWidget] = None
        self.auto_postprocess_checkbox: Optional[QCheckBox] = None
        self.process_selected_btn: Optional[QPushButton] = None
        self.process_all_btn: Optional[QPushButton] = None
        self.postprocess_thread: Optional[PostprocessingThread] = None
        self.movie_mode_title_input: Optional[QLineEdit] = None
        self.movie_mode_year_input: Optional[QLineEdit] = None
        self.merge_videos_btn: Optional[QPushButton] = None
        self.export_single_btn: Optional[QPushButton] = None
        self.rewind_btn: Optional[QPushButton] = None
        self.play_btn: Optional[QPushButton] = None
        self.pause_btn: Optional[QPushButton] = None
        
        # Cover Tab UI references
        self.extract_frames_btn: Optional[QPushButton] = None
        self.generate_cover_btn: Optional[QPushButton] = None
        self.cover_frame_labels: List[QLabel] = []
        self.selected_frame_path: Optional[Path] = None
        self.extracted_frames: List[Path] = []
        self.cover_generation_thread: Optional[QThread] = None
        self.cover_status_label: Optional[QLabel] = None
        self.cover_progress_bar: Optional[QProgressBar] = None
        self.cover_log_text: Optional[QTextEdit] = None
        
        self.init_ui()
        self.update_status("Bereit.")
        
        # Starte Preview automatisch
        QTimer.singleShot(500, self.start_preview)
    
    def setup_logging(self):
        """Richtet Logging ein"""
        log_dir = self.config.get_log_directory()
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f"dv2plex_{datetime.now().strftime('%Y-%m-%d')}.log"
        
        logging.basicConfig(
            level=getattr(logging, self.config.get("logging.level", "INFO")),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
    
    def init_ui(self):
        """Initialisiert die Benutzeroberfläche"""
        self.setWindowTitle("DV2Plex - MiniDV Digitalisierung")
        self.resize(1200, 300)
        
        # Stelle sicher, dass Fenster nicht maximiert ist
        self.setWindowState(Qt.WindowNoState)
        
        # Frameless Window Setup
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Set Global Stylesheet
        self.setStyleSheet(LIQUID_STYLESHEET)
        
        # Haupt-Layout (transparent)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Liquid Container (Abgerundet & Glas-Effekt)
        self.container = LiquidContainer(self)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # Custom Title Bar
        self.title_bar = ModernTitleBar(self, title="DV2Plex - MiniDV Digitalisierung")
        container_layout.addWidget(self.title_bar)
        
        # Verbinde Settings-Button
        self.title_bar.btn_settings.clicked.connect(self.open_settings)
        
        # Content Area
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(12)
        
        self.tabs = QTabWidget()
        content_layout.addWidget(self.tabs)
        
        container_layout.addWidget(content_widget)
        
        # Main Layout zusammenbauen
        # Wir setzen einen Dummy-Widget als Central Widget, damit das Layout greift
        dummy_central = QWidget()
        dummy_central.setLayout(main_layout)
        main_layout.addWidget(self.container)
        self.setCentralWidget(dummy_central)
        
        # Drop Shadow für Tiefenwirkung
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(0)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.container.setGraphicsEffect(shadow)
        
        self.capture_tab = QWidget()
        self.postprocess_tab = QWidget()
        self.movie_mode_tab = QWidget()
        self.cover_tab = QWidget()
        self.tabs.addTab(self.capture_tab, "Digitalisieren")
        self.tabs.addTab(self.postprocess_tab, "Upscaling")
        self.tabs.addTab(self.movie_mode_tab, "Movie Mode")
        self.tabs.addTab(self.cover_tab, "Video Cover")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        
        self._build_capture_tab()
        self._build_postprocess_tab()
        self._build_movie_mode_tab()
        self._build_cover_tab()
    
    def _build_capture_tab(self):
        layout = QHBoxLayout(self.capture_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)
        
        # Preview-Bereich links
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        
        self.preview_label = QLabel("Kein Preview")
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(640, 480)
        preview_layout.addWidget(self.preview_label, stretch=1)
        
        splitter.addWidget(preview_container)
        
        # Steuerbereich rechts
        control_container = QWidget()
        control_layout = QVBoxLayout(control_container)
        control_layout.setSpacing(10)
        
        # Film-Infos
        info_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        title_label = QLabel("Titel")
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("z.B. Las Vegas Urlaub")
        title_box.addWidget(title_label)
        title_box.addWidget(self.title_input)
        
        year_box = QVBoxLayout()
        year_label = QLabel("Jahr")
        self.year_input = QLineEdit()
        self.year_input.setPlaceholderText("2001")
        self.year_input.setMaximumWidth(120)
        year_box.addWidget(year_label)
        year_box.addWidget(self.year_input)
        
        info_layout.addLayout(title_box)
        info_layout.addLayout(year_box)
        control_layout.addLayout(info_layout)
        
        # Auto-Postprocessing Checkbox
        self.auto_postprocess_checkbox = QCheckBox("Postprocessing nach Aufnahme automatisch starten")
        auto_post = bool(self.config.get("capture.auto_postprocess", False))
        self.auto_postprocess_checkbox.setChecked(auto_post)
        self.auto_postprocess_checkbox.stateChanged.connect(self.on_auto_postprocess_changed)
        control_layout.addWidget(self.auto_postprocess_checkbox)
        
        # Kamera-Steuerung Buttons
        camera_control_label = QLabel("Kamera-Steuerung:")
        control_layout.addWidget(camera_control_label)
        
        camera_button_layout = QHBoxLayout()
        
        self.rewind_btn = QPushButton("Rewind")
        self.rewind_btn.clicked.connect(self.rewind_camera)
        camera_button_layout.addWidget(self.rewind_btn)
        
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.play_camera)
        camera_button_layout.addWidget(self.play_btn)
        
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.pause_camera)
        camera_button_layout.addWidget(self.pause_btn)
        
        control_layout.addLayout(camera_button_layout)
        
        # Aufnahme Buttons
        button_layout = QHBoxLayout()
        
        self.capture_start_btn = QPushButton("Aufnahme Start")
        self.capture_start_btn.clicked.connect(self.start_capture)
        button_layout.addWidget(self.capture_start_btn)
        
        self.capture_stop_btn = QPushButton("Aufnahme Stop")
        self.capture_stop_btn.clicked.connect(self.stop_capture)
        self.capture_stop_btn.setEnabled(False)
        button_layout.addWidget(self.capture_stop_btn)
        
        control_layout.addLayout(button_layout)
        
        # Status & Log
        self.status_label = QLabel("Bereit.")
        control_layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        control_layout.addWidget(self.progress_bar)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(180)
        control_layout.addWidget(self.log_text, stretch=1)
        
        control_layout.addStretch()
        splitter.addWidget(control_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
    
    def _build_postprocess_tab(self):
        layout = QVBoxLayout(self.postprocess_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        description = QLabel(
            "Hier siehst du alle digitalisierten Kassetten, die noch nicht vollständig postprocessed wurden."
            "\nMarkiere eine Aufnahme und starte Merge/Upscale/Export entweder für die Auswahl oder für alle."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        
        # Upscaling-Profil-Auswahl (nur im Upscaling-Tab)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Upscaling-Profil:"))
        self.profile_combo = QComboBox()
        profiles = self.config.get("upscaling.profiles", {})
        for profile_name in profiles.keys():
            self.profile_combo.addItem(profile_name)
        default_profile = self.config.get("upscaling.default_profile", "realesrgan_2x")
        index = self.profile_combo.findText(default_profile)
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)
        profile_row.addWidget(self.profile_combo, stretch=1)
        layout.addLayout(profile_row)
        
        self.postprocess_list = QListWidget()
        layout.addWidget(self.postprocess_list, stretch=1)
        
        button_row = QHBoxLayout()
        refresh_btn = QPushButton("Liste aktualisieren")
        refresh_btn.clicked.connect(self.refresh_postprocess_list)
        button_row.addWidget(refresh_btn)
        
        self.process_selected_btn = QPushButton("Auswahl verarbeiten")
        self.process_selected_btn.clicked.connect(self.process_selected_entry)
        button_row.addWidget(self.process_selected_btn)
        
        self.process_all_btn = QPushButton("Alle verarbeiten")
        self.process_all_btn.clicked.connect(self.process_all_pending)
        button_row.addWidget(self.process_all_btn)
        layout.addLayout(button_row)
        
        # Status & Progress für Postprocessing
        self.postprocess_status_label = QLabel("Bereit.")
        layout.addWidget(self.postprocess_status_label)
        
        self.postprocess_progress_bar = QProgressBar()
        self.postprocess_progress_bar.setVisible(False)
        layout.addWidget(self.postprocess_progress_bar)
        
        # Log-Console für Postprocessing
        self.postprocess_log_text = QTextEdit()
        self.postprocess_log_text.setReadOnly(True)
        self.postprocess_log_text.setMinimumHeight(150)
        self.postprocess_log_text.setMaximumHeight(200)
        layout.addWidget(self.postprocess_log_text)
        
        self.refresh_postprocess_list()
    
    def _build_movie_mode_tab(self):
        layout = QVBoxLayout(self.movie_mode_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        description = QLabel(
            "Hier kannst du mehrere upscaled Videos zu einem Film mergen oder einzelne Videos direkt exportieren."
            "\nWähle Videos aus der Liste aus (Multi-Auswahl mit Strg/Ctrl möglich)."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        
        # Film-Info für Merge
        info_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        title_label = QLabel("Film-Titel (für Merge)")
        self.movie_mode_title_input = QLineEdit()
        self.movie_mode_title_input.setPlaceholderText("z.B. Zusammengeschnittener Film")
        title_box.addWidget(title_label)
        title_box.addWidget(self.movie_mode_title_input)
        
        year_box = QVBoxLayout()
        year_label = QLabel("Jahr (für Merge)")
        self.movie_mode_year_input = QLineEdit()
        self.movie_mode_year_input.setPlaceholderText("2001")
        self.movie_mode_year_input.setMaximumWidth(120)
        year_box.addWidget(year_label)
        year_box.addWidget(self.movie_mode_year_input)
        
        info_layout.addLayout(title_box)
        info_layout.addLayout(year_box)
        layout.addLayout(info_layout)
        
        # Video-Liste
        self.movie_mode_list = QListWidget()
        self.movie_mode_list.setSelectionMode(QListWidget.ExtendedSelection)  # Multi-Auswahl
        self.movie_mode_list.itemSelectionChanged.connect(self.on_movie_mode_selection_changed)
        layout.addWidget(self.movie_mode_list, stretch=1)
        
        # Buttons
        button_row = QHBoxLayout()
        refresh_btn = QPushButton("Liste aktualisieren")
        refresh_btn.clicked.connect(self.refresh_movie_mode_list)
        button_row.addWidget(refresh_btn)
        
        self.merge_videos_btn = QPushButton("Videos zu Film mergen")
        self.merge_videos_btn.clicked.connect(self.merge_selected_videos)
        self.merge_videos_btn.setEnabled(False)
        button_row.addWidget(self.merge_videos_btn)
        
        self.export_single_btn = QPushButton("Einzelnes Video exportieren")
        self.export_single_btn.clicked.connect(self.export_single_video)
        self.export_single_btn.setEnabled(False)
        button_row.addWidget(self.export_single_btn)
        layout.addLayout(button_row)
        
        # Status & Progress
        self.movie_mode_status_label = QLabel("Bereit.")
        layout.addWidget(self.movie_mode_status_label)
        
        self.movie_mode_progress_bar = QProgressBar()
        self.movie_mode_progress_bar.setVisible(False)
        layout.addWidget(self.movie_mode_progress_bar)
        
        # Log-Console
        self.movie_mode_log_text = QTextEdit()
        self.movie_mode_log_text.setReadOnly(True)
        self.movie_mode_log_text.setMinimumHeight(150)
        self.movie_mode_log_text.setMaximumHeight(200)
        layout.addWidget(self.movie_mode_log_text)
        
        self.refresh_movie_mode_list()
    
    def log(self, message: str, postprocess_log: bool = False):
        """Fügt eine Nachricht zum Log hinzu"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"{timestamp} - {message}"
        self.log_text.append(log_msg)
        if postprocess_log and hasattr(self, 'postprocess_log_text'):
            self.postprocess_log_text.append(log_msg)
        logging.info(message)
    
    def update_status(self, status: str):
        """Aktualisiert die Status-Anzeige"""
        self.status_label.setText(status)
        self.log(f"Status: {status}")
    
    def start_preview(self, retry_count: int = 0):
        """Startet Live-Preview mit Retry-Logik"""
        if self.capture_engine and self.capture_engine.is_active():
            # Capture liefert bereits Preview-Frames
            return
        if self.preview_thread and self.preview_thread.isRunning():
            return
        
        # Automatische Geräteerkennung
        device_name = self.config.get_firewire_device()
        if not device_name:
            # Versuche automatische Erkennung
            if self.capture_engine:
                device_name = self.capture_engine.detect_firewire_device()
            else:
                # Erstelle temporären CaptureEngine für Geräteerkennung
                ffmpeg_path = self.config.get_ffmpeg_path()
                temp_engine = CaptureEngine(ffmpeg_path)
                device_name = temp_engine.detect_firewire_device()
        
        if not device_name:
            QMessageBox.warning(
                self,
                "Kein Gerät gefunden",
                "Kein FireWire-Gerät gefunden. Bitte verbinden Sie die Kamera und versuchen Sie es erneut.",
            )
            return
        
        ffmpeg_path = self.config.get_ffmpeg_path()
        # Prüfe ob ffmpeg verfügbar ist (kann auch im PATH sein)
        import shutil
        if not ffmpeg_path.exists() and not shutil.which("ffmpeg"):
            QMessageBox.critical(
                self,
                "ffmpeg nicht gefunden",
                f"ffmpeg nicht gefunden: {ffmpeg_path}\nBitte installieren Sie ffmpeg.",
            )
            return
        
        preview_fps = self.config.get("ui.preview_fps", 10)
        self.preview_thread = PreviewThread(ffmpeg_path, device_name, fps=preview_fps)
        self.preview_thread.frame_ready.connect(self.update_preview)
        
        # Fehler-Handler mit Retry
        def on_preview_error(error: str):
            if "I/O error" in error or "Device" in error or "No such device" in error:
                if retry_count < 3:
                    self.log(f"Preview-Verbindungsfehler, versuche erneut ({retry_count + 1}/3)...")
                    # Warte 2 Sekunden, dann Retry
                    QTimer.singleShot(2000, lambda r=retry_count+1: self.start_preview(r))
                else:
                    self.log("Preview-Verbindung fehlgeschlagen nach 3 Versuchen.")
                    self.preview_error(error)
            else:
                self.preview_error(error)
        
        self.preview_thread.error_occurred.connect(on_preview_error)
        self.preview_thread.start()
        self.update_status("Preview läuft...")
    
    def stop_preview(self, keep_frame: bool = False):
        """Stoppt Live-Preview"""
        if self.preview_thread:
            self.preview_thread.stop()
            # PySide6: wait() nimmt Millisekunden als Argument, nicht timeout=
            self.preview_thread.wait(1000)
            self.preview_thread = None
        
        # Nur Label zurücksetzen wenn nicht während Capture
        if not keep_frame and not self.capture_preview_active:
            self.preview_label.clear()
            self.preview_label.setText("Kein Preview")
            if not self.capture_preview_active:
                self.update_status("Preview gestoppt.")
    
    def update_preview(self, image: QImage):
        """Aktualisiert das Preview-Bild"""
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.preview_label.setPixmap(scaled)
        self.preview_label.setAlignment(Qt.AlignCenter)
    
    def preview_error(self, error: str):
        """Behandelt Preview-Fehler"""
        self.log(f"Preview-Fehler: {error}")
        self.stop_preview()
        QMessageBox.warning(self, "Preview-Fehler", f"Fehler beim Preview: {error}")
    
    def start_capture(self):
        """Startet DV-Aufnahme"""
        # Validiere Eingaben
        title = self.title_input.text().strip()
        year = self.year_input.text().strip()
        
        if not title or not year:
            QMessageBox.warning(
                self,
                "Eingabe unvollständig",
                "Bitte geben Sie Titel und Jahr ein."
            )
            return
        
        # Automatische Geräteerkennung
        ffmpeg_path = self.config.get_ffmpeg_path()
        device_path = self.config.get_firewire_device()
        
        # Erstelle CaptureEngine für Geräteerkennung
        self.capture_engine = CaptureEngine(
            ffmpeg_path,
            device_path=device_path,
            log_callback=self.log,
        )
        
        # Automatische Geräteerkennung falls nicht konfiguriert
        device = self.capture_engine.get_device()
        if not device:
            QMessageBox.warning(
                self,
                "Kein Gerät gefunden",
                "Kein FireWire-Gerät gefunden. Bitte verbinden Sie die Kamera und versuchen Sie es erneut."
            )
            return
        
        # Prüfe ffmpeg (kann auch im PATH sein)
        import shutil
        if not ffmpeg_path.exists() and not shutil.which("ffmpeg"):
            QMessageBox.critical(
                self,
                "ffmpeg nicht gefunden",
                f"ffmpeg nicht gefunden: {ffmpeg_path}\nBitte installieren Sie ffmpeg."
            )
            return
        
        # Speichere Film-Info
        self.current_movie_title = title
        self.current_year = year
        movie_name = f"{title} ({year})"
        
        # Erstelle Arbeitsordner
        dv_import_root = self.config.get_dv_import_root()
        self.current_movie_dir = dv_import_root / movie_name
        lowres_dir = self.current_movie_dir / "LowRes"
        lowres_dir.mkdir(parents=True, exist_ok=True)
        
        # Finde nächste Part-Nummer
        existing_parts = list(lowres_dir.glob("part_*.avi"))
        if existing_parts:
            numbers = [int(p.stem.split('_')[1]) for p in existing_parts]
            self.part_number = max(numbers) + 1
        else:
            self.part_number = 1
        
        # Automatischer Workflow-Dialog
        auto_rewind_play = self.config.get("capture.auto_rewind_play", True)
        
        if auto_rewind_play:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Bereit?")
            msg_box.setText("Kassette wird automatisch zurückgespult und abgespielt.\n\nBereit für Aufnahme?")
            msg_box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            
            # Checkbox für Deaktivierung
            checkbox = QCheckBox("Automatisches Rewind/Play deaktivieren")
            msg_box.setCheckBox(checkbox)
            
            reply = msg_box.exec()
            
            if reply != QMessageBox.Ok:
                return
            
            # Aktualisiere auto_rewind_play basierend auf Checkbox
            auto_rewind_play = not checkbox.isChecked()
        else:
            # Frage nach manueller Bedienung
            reply = QMessageBox.question(
                self,
                "Kassette vorbereiten",
                "Bitte spulen Sie die Kassette an den Anfang und drücken Sie Play.\n\n"
                "Wenn die Aufnahme läuft, klicken Sie OK.",
                QMessageBox.Ok | QMessageBox.Cancel
            )
            
            if reply != QMessageBox.Ok:
                return
        
        # Preview wird beim Capture durch den Capture-Stream ersetzt
        self.preview_was_running_before_capture = True
        self.stop_preview(keep_frame=True)
        
        preview_fps = self.config.get("ui.preview_fps", 10)
        
        capture_started = self.capture_engine.start_capture(
            lowres_dir,
            self.part_number,
            preview_callback=self.preview_bridge.frame_ready.emit,
            preview_fps=preview_fps,
            auto_rewind_play=auto_rewind_play,
        )
        
        if capture_started:
            self.capture_preview_active = True
            self.capture_start_btn.setEnabled(False)
            self.capture_stop_btn.setEnabled(True)
            # Deaktiviere Kamera-Steuerung während Aufnahme
            if self.rewind_btn:
                self.rewind_btn.setEnabled(False)
            if self.play_btn:
                self.play_btn.setEnabled(False)
            if self.pause_btn:
                self.pause_btn.setEnabled(False)
            self.update_status(f"Aufnahme läuft... (Part {self.part_number})")
        else:
            self.capture_preview_active = False
            QMessageBox.critical(self, "Fehler", "Aufnahme konnte nicht gestartet werden.")
            QTimer.singleShot(500, self.start_preview)
    
    def stop_capture(self):
        """Stoppt DV-Aufnahme"""
        if self.capture_engine:
            if self.capture_engine.stop_capture():
                self.capture_start_btn.setEnabled(True)
                self.capture_stop_btn.setEnabled(False)
                # Reaktiviere Kamera-Steuerung
                if self.rewind_btn:
                    self.rewind_btn.setEnabled(True)
                if self.play_btn:
                    self.play_btn.setEnabled(True)
                if self.pause_btn:
                    self.pause_btn.setEnabled(True)
                self.update_status("Aufnahme beendet.")
                
                self.capture_preview_active = False
                
                # Preview automatisch wieder starten
                self.log("Starte Preview automatisch neu...")
                QTimer.singleShot(1000, self.start_preview)
                
                auto_post = self.auto_postprocess_checkbox.isChecked() if self.auto_postprocess_checkbox else False
                if auto_post:
                    self.log("Starte automatisches Postprocessing für aktuelle Aufnahme.")
                    self.start_postprocessing(self.current_movie_dir)
                else:
                    self.log("Postprocessing übersprungen. Nutze später den Reiter 'Postprocessing'.")
                    self.refresh_postprocess_list()
            else:
                QMessageBox.warning(self, "Fehler", "Aufnahme konnte nicht gestoppt werden.")
                # Auch bei Fehler Preview wieder starten
                self.capture_preview_active = False
                QTimer.singleShot(1000, self.start_preview)
    
    def rewind_camera(self):
        """Spult die Kassette zurück"""
        if not self.capture_engine:
            # Erstelle temporären CaptureEngine
            ffmpeg_path = self.config.get_ffmpeg_path()
            device_path = self.config.get_firewire_device()
            temp_engine = CaptureEngine(ffmpeg_path, device_path=device_path, log_callback=self.log)
            temp_engine.rewind()
        else:
            self.capture_engine.rewind()
    
    def play_camera(self):
        """Startet die Wiedergabe"""
        if not self.capture_engine:
            # Erstelle temporären CaptureEngine
            ffmpeg_path = self.config.get_ffmpeg_path()
            device_path = self.config.get_firewire_device()
            temp_engine = CaptureEngine(ffmpeg_path, device_path=device_path, log_callback=self.log)
            temp_engine.play()
        else:
            self.capture_engine.play()
    
    def pause_camera(self):
        """Pausiert die Wiedergabe"""
        if not self.capture_engine:
            # Erstelle temporären CaptureEngine
            ffmpeg_path = self.config.get_ffmpeg_path()
            device_path = self.config.get_firewire_device()
            temp_engine = CaptureEngine(ffmpeg_path, device_path=device_path, log_callback=self.log)
            temp_engine.pause()
        else:
            self.capture_engine.pause()
    
    def start_postprocessing(self, movie_dir: Optional[Path] = None) -> bool:
        """Startet Postprocessing (Merge → Upscale → Export) in einem Thread"""
        if movie_dir is None:
            movie_dir = self.current_movie_dir
        
        if not movie_dir or not movie_dir.exists():
            QMessageBox.warning(
                self,
                "Kein Film ausgewählt",
                "Bitte wähle im Reiter 'Postprocessing' einen Film aus oder starte zuerst eine Aufnahme.",
            )
            return False
        
        # Prüfe ob bereits ein Postprocessing läuft
        if self.postprocess_thread and self.postprocess_thread.isRunning():
            QMessageBox.warning(
                self,
                "Postprocessing läuft bereits",
                "Bitte warte, bis das aktuelle Postprocessing abgeschlossen ist."
            )
            return False
        
        # Leere Postprocessing-Log
        if hasattr(self, 'postprocess_log_text'):
            self.postprocess_log_text.clear()
        
        # Buttons deaktivieren
        if self.process_selected_btn:
            self.process_selected_btn.setEnabled(False)
        if self.process_all_btn:
            self.process_all_btn.setEnabled(False)
        
        # Profil auswählen
        profile_name = self.profile_combo.currentText() if hasattr(self, 'profile_combo') and self.profile_combo else self.config.get("upscaling.default_profile", "realesrgan_2x")
        
        # Thread erstellen und starten
        self.postprocess_thread = PostprocessingThread(self.config, movie_dir, profile_name)
        self.postprocess_thread.progress.connect(self._on_postprocess_progress)
        self.postprocess_thread.status.connect(self._on_postprocess_status)
        self.postprocess_thread.log_message.connect(self._on_postprocess_log)
        self.postprocess_thread.finished.connect(self._on_postprocess_finished)
        self.postprocess_thread.start()
        
        return True
    
    def _on_postprocess_progress(self, value: int):
        """Callback für Postprocessing-Fortschritt"""
        if hasattr(self, 'postprocess_progress_bar'):
            self.postprocess_progress_bar.setVisible(True)
            self.postprocess_progress_bar.setValue(value)
    
    def _on_postprocess_status(self, status: str):
        """Callback für Postprocessing-Status"""
        if hasattr(self, 'postprocess_status_label'):
            self.postprocess_status_label.setText(status)
    
    def _on_postprocess_log(self, message: str):
        """Callback für Postprocessing-Log"""
        if hasattr(self, 'postprocess_log_text'):
            self.postprocess_log_text.append(message)
        # Auch ins Hauptlog
        self.log(message)
    
    def _on_postprocess_finished(self, success: bool, message: str):
        """Callback wenn Postprocessing fertig ist"""
        if hasattr(self, 'postprocess_progress_bar'):
            self.postprocess_progress_bar.setVisible(False)
        
        if hasattr(self, 'postprocess_status_label'):
            self.postprocess_status_label.setText("Bereit." if success else "Fehler!")
        
        # Buttons wieder aktivieren
        if self.process_selected_btn:
            self.process_selected_btn.setEnabled(True)
        if self.process_all_btn:
            self.process_all_btn.setEnabled(True)
        
        # Liste aktualisieren
        self.refresh_postprocess_list()
        
        # Nachricht anzeigen
        if success:
            QMessageBox.information(self, "Erfolg", message)
        else:
            QMessageBox.critical(self, "Fehler", message)
    
    def _parse_movie_folder_name(self, folder_name: str) -> tuple[str, str]:
        match = re.match(r"(.+)\s+\((\d{4})\)$", folder_name)
        if match:
            return match.group(1).strip(), match.group(2)
        return folder_name, ""
    
    def find_pending_movies(self) -> List[Path]:
        pending: List[Path] = []
        dv_root = self.config.get_dv_import_root()
        if not dv_root.exists():
            return pending
        for movie_dir in sorted(dv_root.iterdir()):
            if not movie_dir.is_dir():
                continue
            lowres_dir = movie_dir / "LowRes"
            if not lowres_dir.exists():
                continue
            parts = list(lowres_dir.glob("part_*.avi"))
            if not parts:
                continue
            highres_dir = movie_dir / "HighRes"
            expected_file = highres_dir / f"{movie_dir.name}_4k.mp4"
            if not expected_file.exists():
                pending.append(movie_dir)
        return pending
    
    def refresh_postprocess_list(self):
        if not self.postprocess_list:
            return
        self.postprocess_list.clear()
        pending = self.find_pending_movies()
        if not pending:
            item = QListWidgetItem("Keine offenen Projekte 🎉")
            item.setFlags(Qt.NoItemFlags)
            self.postprocess_list.addItem(item)
            self._set_postprocess_buttons_enabled(False)
            return
        for movie_dir in pending:
            title, year = self._parse_movie_folder_name(movie_dir.name)
            display = f"{title} ({year})" if year else movie_dir.name
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, str(movie_dir))
            self.postprocess_list.addItem(item)
        self._set_postprocess_buttons_enabled(True)
    
    def _set_postprocess_buttons_enabled(self, enabled: bool):
        if self.process_selected_btn:
            self.process_selected_btn.setEnabled(enabled)
        if self.process_all_btn:
            self.process_all_btn.setEnabled(enabled)
    
    def process_selected_entry(self):
        if not self.postprocess_list:
            return
        item = self.postprocess_list.currentItem()
        path_value = item.data(Qt.UserRole) if item else None
        if not path_value:
            QMessageBox.information(
                self,
                "Keine Auswahl",
                "Bitte wähle einen Eintrag aus der Liste aus.",
            )
            return
        movie_dir = Path(path_value)
        self._set_postprocess_buttons_enabled(False)
        try:
            self.start_postprocessing(movie_dir)
        finally:
            self._set_postprocess_buttons_enabled(True)
            self.refresh_postprocess_list()
    
    def process_all_pending(self):
        pending = self.find_pending_movies()
        if not pending:
            QMessageBox.information(self, "Nichts zu tun", "Alle Filme sind bereits verarbeitet.")
            return
        confirm = QMessageBox.question(
            self,
            "Alle verarbeiten?",
            f"Es werden {len(pending)} Filme verarbeitet. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._set_postprocess_buttons_enabled(False)
        try:
            for movie_dir in pending:
                self.start_postprocessing(movie_dir)
        finally:
            self._set_postprocess_buttons_enabled(True)
            self.refresh_postprocess_list()
    
    def on_auto_postprocess_changed(self, state: int):
        value = state == Qt.Checked
        self.config.set("capture.auto_postprocess", value)
        self.config.save_config()
    
    def on_tab_changed(self, index: int):
        if self.tabs and self.postprocess_tab and index == self.tabs.indexOf(self.postprocess_tab):
            self.refresh_postprocess_list()
        elif self.tabs and self.movie_mode_tab and index == self.tabs.indexOf(self.movie_mode_tab):
            self.refresh_movie_mode_list()
        elif self.tabs and self.cover_tab and index == self.tabs.indexOf(self.cover_tab):
            self.refresh_cover_video_list()
    
    def choose_plex_folder(self):
        """Öffnet Dialog zur Auswahl des Plex-Movies-Ordners"""
        current_path = self.config.get_plex_movies_root()
        folder = QFileDialog.getExistingDirectory(
            self,
            "Plex Movies Ordner wählen",
            str(current_path) if current_path.exists() else ""
        )
        
        if folder:
            self.config.set("paths.plex_movies_root", folder)
            self.config.save_config()
            self.log(f"Plex Movies Ordner gesetzt: {folder}")
    
    def find_upscaled_videos(self) -> List[tuple[Path, str, str]]:
        """
        Findet alle upscaled Videos in HighRes-Ordnern
        
        Returns:
            Liste von Tupeln: (video_path, title, year)
        """
        videos = []
        dv_root = self.config.get_dv_import_root()
        if not dv_root.exists():
            return videos
        
        for movie_dir in sorted(dv_root.iterdir()):
            if not movie_dir.is_dir():
                continue
            highres_dir = movie_dir / "HighRes"
            if not highres_dir.exists():
                continue
            
            # Suche nach *_4k.mp4 Dateien
            for video_file in highres_dir.glob("*_4k.mp4"):
                title, year = self._parse_movie_folder_name(movie_dir.name)
                videos.append((video_file, title, year))
        
        return videos
    
    def refresh_movie_mode_list(self):
        """Aktualisiert die Liste der verfügbaren upscaled Videos"""
        if not self.movie_mode_list:
            return
        self.movie_mode_list.clear()
        videos = self.find_upscaled_videos()
        
        if not videos:
            item = QListWidgetItem("Keine upscaled Videos gefunden")
            item.setFlags(Qt.NoItemFlags)
            self.movie_mode_list.addItem(item)
            return
        
        for video_path, title, year in videos:
            display = f"{title} ({year})" if year else f"{title} - {video_path.name}"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, str(video_path))
            item.setData(Qt.UserRole + 1, title)  # Titel speichern
            item.setData(Qt.UserRole + 2, year)   # Jahr speichern
            self.movie_mode_list.addItem(item)
    
    def on_movie_mode_selection_changed(self):
        """Aktiviert/deaktiviert Buttons basierend auf Auswahl"""
        if not self.movie_mode_list:
            return
        
        selected_items = self.movie_mode_list.selectedItems()
        count = len(selected_items)
        
        # Merge-Button: mindestens 2 Videos
        if self.merge_videos_btn:
            self.merge_videos_btn.setEnabled(count >= 2)
        
        # Export-Button: genau 1 Video
        if self.export_single_btn:
            self.export_single_btn.setEnabled(count == 1)
    
    def merge_selected_videos(self):
        """Merged die ausgewählten Videos zu einem Film"""
        if not self.movie_mode_list:
            return
        
        selected_items = self.movie_mode_list.selectedItems()
        if len(selected_items) < 2:
            QMessageBox.warning(
                self,
                "Ungültige Auswahl",
                "Bitte wähle mindestens 2 Videos zum Mergen aus."
            )
            return
        
        # Validiere Titel und Jahr
        title = self.movie_mode_title_input.text().strip() if self.movie_mode_title_input else ""
        year = self.movie_mode_year_input.text().strip() if self.movie_mode_year_input else ""
        
        if not title or not year:
            QMessageBox.warning(
                self,
                "Eingabe unvollständig",
                "Bitte gib Titel und Jahr für den gemergten Film ein."
            )
            return
        
        # Sammle Video-Pfade
        video_paths = []
        for item in selected_items:
            path_str = item.data(Qt.UserRole)
            if path_str:
                video_paths.append(Path(path_str))
        
        if not video_paths:
            QMessageBox.warning(self, "Fehler", "Keine gültigen Videos ausgewählt.")
            return
        
        # Bestätigung
        reply = QMessageBox.question(
            self,
            "Videos mergen?",
            f"Es werden {len(video_paths)} Videos zu '{title} ({year})' gemerged.\nFortfahren?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Merge durchführen
        self.movie_mode_status_label.setText("Merge läuft...")
        self.movie_mode_progress_bar.setVisible(True)
        self.movie_mode_progress_bar.setValue(0)
        self.movie_mode_log_text.clear()
        
        # Erstelle temporäre Ausgabedatei
        temp_dir = Path(tempfile.gettempdir()) / "dv2plex_merge"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_output = temp_dir / f"{title}_{year}_merged.mp4"
        
        try:
            # Merge
            merge_engine = MergeEngine(
                self.config.get_ffmpeg_path(),
                log_callback=lambda msg: self.movie_mode_log_text.append(msg)
            )
            
            self.movie_mode_log_text.append(f"=== Starte Merge: {len(video_paths)} Videos ===")
            merged_file = merge_engine.merge_videos(video_paths, temp_output)
            
            if not merged_file or not merged_file.exists():
                QMessageBox.critical(self, "Fehler", "Merge fehlgeschlagen!")
                self.movie_mode_status_label.setText("Fehler!")
                self.movie_mode_progress_bar.setVisible(False)
                return
            
            self.movie_mode_progress_bar.setValue(50)
            self.movie_mode_log_text.append("=== Merge erfolgreich, starte Export ===")
            
            # Export nach PlexMovies
            plex_exporter = PlexExporter(
                self.config.get_plex_movies_root(),
                log_callback=lambda msg: self.movie_mode_log_text.append(msg)
            )
            
            result = plex_exporter.export_movie(merged_file, title, year, overwrite=True)
            
            if result:
                self.movie_mode_progress_bar.setValue(100)
                self.movie_mode_status_label.setText("Erfolgreich!")
                QMessageBox.information(
                    self,
                    "Erfolg",
                    f"Videos erfolgreich gemerged und exportiert:\n{result}"
                )
                # Lösche temporäre Datei
                try:
                    merged_file.unlink()
                except:
                    pass
            else:
                QMessageBox.warning(self, "Fehler", "Export fehlgeschlagen!")
                self.movie_mode_status_label.setText("Export fehlgeschlagen!")
            
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Unerwarteter Fehler: {e}")
            self.movie_mode_status_label.setText("Fehler!")
        finally:
            self.movie_mode_progress_bar.setVisible(False)
            self.refresh_movie_mode_list()
    
    def export_single_video(self):
        """Exportiert ein einzelnes ausgewähltes Video"""
        if not self.movie_mode_list:
            return
        
        selected_items = self.movie_mode_list.selectedItems()
        if len(selected_items) != 1:
            QMessageBox.warning(
                self,
                "Ungültige Auswahl",
                "Bitte wähle genau ein Video zum Exportieren aus."
            )
            return
        
        item = selected_items[0]
        path_str = item.data(Qt.UserRole)
        title = item.data(Qt.UserRole + 1) or ""
        year = item.data(Qt.UserRole + 2) or ""
        
        if not path_str:
            QMessageBox.warning(self, "Fehler", "Kein gültiges Video ausgewählt.")
            return
        
        video_path = Path(path_str)
        if not video_path.exists():
            QMessageBox.warning(self, "Fehler", f"Video nicht gefunden: {video_path}")
            return
        
        # Bestätigung
        display_name = f"{title} ({year})" if year else title or video_path.name
        reply = QMessageBox.question(
            self,
            "Video exportieren?",
            f"Video '{display_name}' wird nach PlexMovies exportiert.\nFortfahren?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Export durchführen
        self.movie_mode_status_label.setText("Export läuft...")
        self.movie_mode_progress_bar.setVisible(True)
        self.movie_mode_progress_bar.setValue(0)
        self.movie_mode_log_text.clear()
        
        try:
            plex_exporter = PlexExporter(
                self.config.get_plex_movies_root(),
                log_callback=lambda msg: self.movie_mode_log_text.append(msg)
            )
            
            self.movie_mode_log_text.append(f"=== Starte Export: {display_name} ===")
            result = plex_exporter.export_single_video(video_path, title if title else None, year if year else None, overwrite=True)
            
            if result:
                self.movie_mode_progress_bar.setValue(100)
                self.movie_mode_status_label.setText("Erfolgreich!")
                QMessageBox.information(
                    self,
                    "Erfolg",
                    f"Video erfolgreich exportiert:\n{result}"
                )
            else:
                QMessageBox.warning(self, "Fehler", "Export fehlgeschlagen!")
                self.movie_mode_status_label.setText("Export fehlgeschlagen!")
            
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Unerwarteter Fehler: {e}")
            self.movie_mode_status_label.setText("Fehler!")
        finally:
            self.movie_mode_progress_bar.setVisible(False)
    
    def _build_cover_tab(self):
        """Erstellt den Video Cover Tab"""
        layout = QVBoxLayout(self.cover_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        description = QLabel(
            "Wähle ein Video aus und generiere ein Plex Movie Cover aus einem Frame.\n"
            "Das System extrahiert 4 zufällige Frames, aus denen du einen auswählen kannst."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        
        # Video-Auswahl
        video_label = QLabel("Verfügbare Videos:")
        layout.addWidget(video_label)
        
        self.cover_video_list = QListWidget()
        self.cover_video_list.itemSelectionChanged.connect(self.on_cover_video_selected)
        layout.addWidget(self.cover_video_list, stretch=1)
        
        # Buttons für Video-Auswahl
        video_button_row = QHBoxLayout()
        refresh_videos_btn = QPushButton("Liste aktualisieren")
        refresh_videos_btn.clicked.connect(self.refresh_cover_video_list)
        video_button_row.addWidget(refresh_videos_btn)
        
        self.extract_frames_btn = QPushButton("Frames extrahieren")
        self.extract_frames_btn.clicked.connect(self.extract_frames)
        self.extract_frames_btn.setEnabled(False)
        video_button_row.addWidget(self.extract_frames_btn)
        layout.addLayout(video_button_row)
        
        # Frame-Thumbnail-Grid
        frames_label = QLabel("Extrahierte Frames (klicke zum Auswählen):")
        layout.addWidget(frames_label)
        
        frames_container = QWidget()
        frames_layout = QGridLayout(frames_container)
        frames_layout.setSpacing(10)
        
        self.cover_frame_labels = []
        for i in range(4):
            frame_label = QLabel("Kein Frame")
            frame_label.setAlignment(Qt.AlignCenter)
            frame_label.setMinimumSize(200, 150)
            frame_label.setMaximumSize(200, 150)
            frame_label.setStyleSheet("""
                QLabel {
                    background-color: rgba(0, 0, 0, 0.6);
                    border: 2px solid rgba(255, 255, 255, 0.1);
                    border-radius: 8px;
                }
                QLabel:hover {
                    border: 2px solid rgba(0, 210, 255, 0.6);
                }
            """)
            frame_label.mousePressEvent = lambda event, idx=i: self.on_frame_clicked(idx)
            frames_layout.addWidget(frame_label, i // 2, i % 2)
            self.cover_frame_labels.append(frame_label)
        
        layout.addWidget(frames_container)
        
        # Cover-Generierung Button
        self.generate_cover_btn = QPushButton("Cover generieren")
        self.generate_cover_btn.clicked.connect(self.generate_cover)
        self.generate_cover_btn.setEnabled(False)
        layout.addWidget(self.generate_cover_btn)
        
        # Status & Progress
        self.cover_status_label = QLabel("Bereit.")
        layout.addWidget(self.cover_status_label)
        
        self.cover_progress_bar = QProgressBar()
        self.cover_progress_bar.setVisible(False)
        layout.addWidget(self.cover_progress_bar)
        
        # Log-Console
        self.cover_log_text = QTextEdit()
        self.cover_log_text.setReadOnly(True)
        self.cover_log_text.setMinimumHeight(150)
        self.cover_log_text.setMaximumHeight(200)
        layout.addWidget(self.cover_log_text)
        
        self.refresh_cover_video_list()
    
    def find_available_videos(self) -> List[tuple[Path, str, str]]:
        """
        Findet alle verfügbaren Videos (aus Plex Movies Root und HighRes-Ordnern)
        
        Returns:
            Liste von Tupeln: (video_path, title, year)
        """
        videos = []
        
        # 1. Suche in Plex Movies Root
        plex_root = self.config.get_plex_movies_root()
        if plex_root.exists():
            for movie_dir in sorted(plex_root.iterdir()):
                if not movie_dir.is_dir():
                    continue
                
                # Suche nach .mp4 Dateien im Movie-Ordner
                for video_file in movie_dir.glob("*.mp4"):
                    title, year = self._parse_movie_folder_name(movie_dir.name)
                    videos.append((video_file, title, year))
        
        # 2. Suche in HighRes-Ordnern
        dv_root = self.config.get_dv_import_root()
        if dv_root.exists():
            for movie_dir in sorted(dv_root.iterdir()):
                if not movie_dir.is_dir():
                    continue
                
                highres_dir = movie_dir / "HighRes"
                if highres_dir.exists():
                    for video_file in highres_dir.glob("*_4k.mp4"):
                        title, year = self._parse_movie_folder_name(movie_dir.name)
                        videos.append((video_file, title, year))
        
        return videos
    
    def refresh_cover_video_list(self):
        """Aktualisiert die Liste der verfügbaren Videos"""
        if not self.cover_video_list:
            return
        
        self.cover_video_list.clear()
        videos = self.find_available_videos()
        
        if not videos:
            item = QListWidgetItem("Keine Videos gefunden")
            item.setFlags(Qt.NoItemFlags)
            self.cover_video_list.addItem(item)
            return
        
        for video_path, title, year in videos:
            display = f"{title} ({year})" if year else f"{title} - {video_path.name}"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, str(video_path))
            item.setData(Qt.UserRole + 1, title)
            item.setData(Qt.UserRole + 2, year)
            self.cover_video_list.addItem(item)
    
    def on_cover_video_selected(self):
        """Handler für Video-Auswahl"""
        if not self.cover_video_list:
            return
        
        selected = self.cover_video_list.currentItem()
        if selected and selected.data(Qt.UserRole):
            self.extract_frames_btn.setEnabled(True)
            # Lösche vorherige Frames
            self.clear_frame_previews()
        else:
            self.extract_frames_btn.setEnabled(False)
    
    def extract_frames(self):
        """Extrahiert zufällige Frames aus dem ausgewählten Video"""
        if not self.cover_video_list:
            return
        
        selected = self.cover_video_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Keine Auswahl", "Bitte wähle ein Video aus.")
            return
        
        video_path_str = selected.data(Qt.UserRole)
        if not video_path_str:
            return
        
        video_path = Path(video_path_str)
        if not video_path.exists():
            QMessageBox.warning(self, "Fehler", f"Video nicht gefunden: {video_path}")
            return
        
        # Deaktiviere Button während Extraktion
        self.extract_frames_btn.setEnabled(False)
        self.cover_status_label.setText("Extrahiere Frames...")
        self.cover_log_text.clear()
        self.cover_log_text.append(f"Extrahiere Frames aus: {video_path.name}")
        
        # Lösche vorherige Frames
        self.clear_frame_previews()
        
        try:
            # Erstelle FrameExtractionEngine
            frame_engine = FrameExtractionEngine(
                self.config.get_ffmpeg_path(),
                log_callback=lambda msg: self.cover_log_text.append(msg)
            )
            
            # Extrahiere Frames
            self.extracted_frames = frame_engine.extract_random_frames(video_path, count=4)
            
            if not self.extracted_frames:
                QMessageBox.warning(self, "Fehler", "Konnte keine Frames extrahieren.")
                self.cover_status_label.setText("Fehler bei Frame-Extraktion")
                self.extract_frames_btn.setEnabled(True)
                return
            
            # Zeige Frames als Thumbnails
            self.display_frames(self.extracted_frames)
            
            self.cover_status_label.setText(f"{len(self.extracted_frames)} Frames extrahiert")
            self.cover_log_text.append(f"✓ {len(self.extracted_frames)} Frames erfolgreich extrahiert")
            
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Fehler bei Frame-Extraktion: {e}")
            self.cover_status_label.setText("Fehler!")
            self.cover_log_text.append(f"Fehler: {e}")
        finally:
            self.extract_frames_btn.setEnabled(True)
    
    def clear_frame_previews(self):
        """Löscht die Frame-Previews"""
        self.selected_frame_path = None
        self.extracted_frames = []
        for label in self.cover_frame_labels:
            label.clear()
            label.setText("Kein Frame")
            label.setStyleSheet("""
                QLabel {
                    background-color: rgba(0, 0, 0, 0.6);
                    border: 2px solid rgba(255, 255, 255, 0.1);
                    border-radius: 8px;
                }
                QLabel:hover {
                    border: 2px solid rgba(0, 210, 255, 0.6);
                }
            """)
        self.generate_cover_btn.setEnabled(False)
    
    def display_frames(self, frame_paths: List[Path]):
        """Zeigt Frames als Thumbnails an"""
        for i, frame_path in enumerate(frame_paths):
            if i >= len(self.cover_frame_labels):
                break
            
            try:
                pixmap = QPixmap(str(frame_path))
                scaled = pixmap.scaled(
                    200, 150,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.cover_frame_labels[i].setPixmap(scaled)
                self.cover_frame_labels[i].setText("")
            except Exception as e:
                self.cover_log_text.append(f"Fehler beim Laden von Frame {i+1}: {e}")
    
    def on_frame_clicked(self, index: int):
        """Handler für Frame-Klick (Auswahl)"""
        if index >= len(self.extracted_frames):
            return
        
        selected_frame = self.extracted_frames[index]
        self.selected_frame_path = selected_frame
        
        # Visualisiere Auswahl: Markiere ausgewähltes Frame
        for i, label in enumerate(self.cover_frame_labels):
            if i == index:
                label.setStyleSheet("""
                    QLabel {
                        background-color: rgba(0, 0, 0, 0.6);
                        border: 3px solid rgba(0, 210, 255, 1.0);
                        border-radius: 8px;
                    }
                """)
            else:
                label.setStyleSheet("""
                    QLabel {
                        background-color: rgba(0, 0, 0, 0.6);
                        border: 2px solid rgba(255, 255, 255, 0.1);
                        border-radius: 8px;
                    }
                    QLabel:hover {
                        border: 2px solid rgba(0, 210, 255, 0.6);
                    }
                """)
        
        self.generate_cover_btn.setEnabled(True)
        self.cover_status_label.setText(f"Frame {index+1} ausgewählt")
    
    def generate_cover(self):
        """Startet die Cover-Generierung in einem Thread"""
        if not self.selected_frame_path or not self.selected_frame_path.exists():
            QMessageBox.warning(self, "Keine Auswahl", "Bitte wähle einen Frame aus.")
            return
        
        # Prüfe ob bereits eine Generierung läuft
        if self.cover_generation_thread and self.cover_generation_thread.isRunning():
            QMessageBox.warning(
                self,
                "Generierung läuft",
                "Bitte warte, bis die aktuelle Cover-Generierung abgeschlossen ist."
            )
            return
        
        # Hole Video-Info für Cover-Speicherung
        selected_video = self.cover_video_list.currentItem()
        if not selected_video:
            QMessageBox.warning(self, "Fehler", "Kein Video ausgewählt.")
            return
        
        title = selected_video.data(Qt.UserRole + 1) or ""
        year = selected_video.data(Qt.UserRole + 2) or ""
        
        if not title:
            # Versuche Titel aus Video-Pfad zu extrahieren
            video_path_str = selected_video.data(Qt.UserRole)
            if video_path_str:
                video_path = Path(video_path_str)
                title = video_path.stem
        
        # Deaktiviere Button
        self.generate_cover_btn.setEnabled(False)
        self.cover_status_label.setText("Generiere Cover...")
        self.cover_progress_bar.setVisible(True)
        self.cover_progress_bar.setValue(0)
        self.cover_log_text.append("=== Starte Cover-Generierung ===")
        
        # Erstelle Thread
        self.cover_generation_thread = CoverGenerationThread(
            self.config,
            self.selected_frame_path,
            title,
            year,
            log_callback=lambda msg: self.cover_log_text.append(msg)
        )
        self.cover_generation_thread.progress.connect(self._on_cover_progress)
        self.cover_generation_thread.status.connect(self._on_cover_status)
        self.cover_generation_thread.finished.connect(self._on_cover_finished)
        self.cover_generation_thread.start()
    
    def _on_cover_progress(self, value: int):
        """Callback für Cover-Generierungs-Fortschritt"""
        if self.cover_progress_bar:
            self.cover_progress_bar.setValue(value)
    
    def _on_cover_status(self, status: str):
        """Callback für Cover-Generierungs-Status"""
        if self.cover_status_label:
            self.cover_status_label.setText(status)
    
    def _on_cover_finished(self, success: bool, message: str):
        """Callback wenn Cover-Generierung fertig ist"""
        if self.cover_progress_bar:
            self.cover_progress_bar.setVisible(False)
        
        if self.cover_status_label:
            self.cover_status_label.setText("Bereit." if success else "Fehler!")
        
        self.generate_cover_btn.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "Erfolg", message)
        else:
            QMessageBox.critical(self, "Fehler", message)
    
    def open_settings(self):
        """Öffnet das Settings-Dialog-Fenster"""
        dialog = SettingsDialog(self)
        dialog.exec()


class CoverGenerationThread(QThread):
    """Thread für Cover-Generierung im Hintergrund"""
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(bool, str)  # success, message
    
    def __init__(
        self,
        config: Config,
        frame_path: Path,
        title: str,
        year: str,
        log_callback: Optional[Callable] = None
    ):
        super().__init__()
        self.config = config
        self.frame_path = frame_path
        self.title = title
        self.year = year
        self.log_callback = log_callback
        self._stop_requested = False
    
    def run(self):
        """Führt Cover-Generierung aus"""
        try:
            self.status.emit("Lade Stable Diffusion Modell...")
            self.progress.emit(10)
            
            # Hole Config-Werte
            model_id = self.config.get("cover.default_model", "runwayml/stable-diffusion-v1-5")
            prompt = self.config.get("cover.default_prompt", CoverGenerationEngine.DEFAULT_PROMPT)
            strength = self.config.get("cover.strength", 0.6)
            guidance_scale = self.config.get("cover.guidance_scale", 8.0)
            num_steps = self.config.get("cover.num_inference_steps", 50)
            
            # Parse output_size
            size_str = self.config.get("cover.output_size", "1000x1500")
            try:
                width, height = map(int, size_str.split("x"))
                output_size = (width, height)
            except:
                output_size = (1000, 1500)
            
            # Erstelle CoverGenerationEngine
            cover_engine = CoverGenerationEngine(
                model_id=model_id,
                log_callback=self.log
            )
            
            self.progress.emit(30)
            self.status.emit("Generiere Cover...")
            
            # Erstelle temporäres Ausgabeverzeichnis
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / "dv2plex_covers"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_cover = temp_dir / f"cover_{self.frame_path.stem}.jpg"
            
            # Generiere Cover
            result_path = cover_engine.generate_cover(
                self.frame_path,
                temp_cover,
                prompt=prompt,
                strength=strength,
                guidance_scale=guidance_scale,
                num_inference_steps=num_steps,
                output_size=output_size
            )
            
            if not result_path or not result_path.exists():
                self.finished.emit(False, "Cover-Generierung fehlgeschlagen!")
                return
            
            self.progress.emit(80)
            self.status.emit("Speichere Cover...")
            
            # Speichere Cover im Plex Movies Ordner
            plex_exporter = PlexExporter(
                self.config.get_plex_movies_root(),
                log_callback=self.log
            )
            
            saved_path = plex_exporter.save_cover(
                result_path,
                self.title,
                self.year,
                overwrite=True
            )
            
            if saved_path:
                self.progress.emit(100)
                self.finished.emit(
                    True,
                    f"Cover erfolgreich generiert und gespeichert:\n{saved_path}"
                )
            else:
                self.finished.emit(
                    False,
                    "Cover generiert, aber Speicherung fehlgeschlagen!"
                )
            
        except Exception as e:
            import traceback
            error_msg = f"Fehler bei Cover-Generierung: {e}\n{traceback.format_exc()}"
            self.log(error_msg)
            self.finished.emit(False, error_msg)
    
    def log(self, message: str):
        """Loggt eine Nachricht"""
        if self.log_callback:
            self.log_callback(message)


class SettingsDialog(QDialog):
    """Dialog-Fenster für Einstellungen"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = parent.config if parent else Config()
        self.setWindowTitle("Einstellungen")
        self.setMinimumSize(600, 700)
        self.setModal(True)
        
        # Frameless Window Setup (passend zum Liquid Design)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Set Stylesheet
        self.setStyleSheet(LIQUID_STYLESHEET)
        
        self._build_ui()
        self._load_settings()
    
    def _build_ui(self):
        """Erstellt die UI-Elemente"""
        # Haupt-Layout (transparent)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Liquid Container (Abgerundet & Glas-Effekt)
        container = LiquidContainer(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(15)
        
        # Drop Shadow für Tiefenwirkung
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(0)
        shadow.setColor(QColor(0, 0, 0, 150))
        container.setGraphicsEffect(shadow)
        
        main_layout.addWidget(container)
        
        # ScrollArea für alle Einstellungen
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_layout.setSpacing(15)
        
        # Pfade-Sektion
        paths_group = QGroupBox("Pfade")
        paths_layout = QVBoxLayout()
        paths_layout.setSpacing(10)
        
        # Plex Movies Root
        plex_layout = QHBoxLayout()
        plex_layout.addWidget(QLabel("Plex Movies Root:"))
        self.plex_movies_edit = QLineEdit()
        self.plex_movies_edit.setPlaceholderText("Pfad zum Plex Movies Ordner")
        plex_browse_btn = QPushButton("Durchsuchen...")
        plex_browse_btn.clicked.connect(self._on_browse_plex_movies)
        plex_layout.addWidget(self.plex_movies_edit)
        plex_layout.addWidget(plex_browse_btn)
        paths_layout.addLayout(plex_layout)
        
        # DV Import Root
        dv_layout = QHBoxLayout()
        dv_layout.addWidget(QLabel("DV Import Root (DV_Cache):"))
        self.dv_import_edit = QLineEdit()
        self.dv_import_edit.setPlaceholderText("Pfad zum DV Import Ordner")
        dv_browse_btn = QPushButton("Durchsuchen...")
        dv_browse_btn.clicked.connect(self._on_browse_dv_import)
        dv_layout.addWidget(self.dv_import_edit)
        dv_layout.addWidget(dv_browse_btn)
        paths_layout.addLayout(dv_layout)
        
        # ffmpeg Path
        ffmpeg_layout = QHBoxLayout()
        ffmpeg_layout.addWidget(QLabel("ffmpeg Pfad:"))
        self.ffmpeg_edit = QLineEdit()
        self.ffmpeg_edit.setPlaceholderText("Leer lassen für System-PATH")
        ffmpeg_browse_btn = QPushButton("Durchsuchen...")
        ffmpeg_browse_btn.clicked.connect(self._on_browse_ffmpeg)
        ffmpeg_layout.addWidget(self.ffmpeg_edit)
        ffmpeg_layout.addWidget(ffmpeg_browse_btn)
        paths_layout.addLayout(ffmpeg_layout)
        
        # RealESRGAN Path
        realesrgan_layout = QHBoxLayout()
        realesrgan_layout.addWidget(QLabel("RealESRGAN Pfad:"))
        self.realesrgan_edit = QLineEdit()
        self.realesrgan_edit.setPlaceholderText("Leer lassen für System-PATH")
        realesrgan_browse_btn = QPushButton("Durchsuchen...")
        realesrgan_browse_btn.clicked.connect(self._on_browse_realesrgan)
        realesrgan_layout.addWidget(self.realesrgan_edit)
        realesrgan_layout.addWidget(realesrgan_browse_btn)
        paths_layout.addLayout(realesrgan_layout)
        
        paths_group.setLayout(paths_layout)
        scroll_layout.addWidget(paths_group)
        
        # Device-Sektion
        device_group = QGroupBox("Gerät")
        device_layout = QVBoxLayout()
        device_layout.setSpacing(10)
        
        # FireWire Device
        fw_layout = QHBoxLayout()
        fw_layout.addWidget(QLabel("FireWire Device:"))
        self.firewire_edit = QLineEdit()
        self.firewire_edit.setPlaceholderText("Leer lassen für Auto-Detection")
        fw_layout.addWidget(self.firewire_edit)
        device_layout.addLayout(fw_layout)
        
        device_group.setLayout(device_layout)
        scroll_layout.addWidget(device_group)
        
        # Capture-Optionen
        capture_group = QGroupBox("Aufnahme")
        capture_layout = QVBoxLayout()
        capture_layout.setSpacing(10)
        
        self.auto_postprocess_checkbox = QCheckBox("Auto-Postprocess")
        capture_layout.addWidget(self.auto_postprocess_checkbox)
        
        self.auto_upscale_checkbox = QCheckBox("Auto-Upscale")
        capture_layout.addWidget(self.auto_upscale_checkbox)
        
        self.auto_export_checkbox = QCheckBox("Auto-Export")
        capture_layout.addWidget(self.auto_export_checkbox)
        
        self.auto_rewind_play_checkbox = QCheckBox("Auto-Rewind/Play")
        capture_layout.addWidget(self.auto_rewind_play_checkbox)
        
        self.timestamp_overlay_checkbox = QCheckBox("Timestamp Overlay")
        capture_layout.addWidget(self.timestamp_overlay_checkbox)
        
        # Timestamp Duration
        timestamp_layout = QHBoxLayout()
        timestamp_layout.addWidget(QLabel("Timestamp Dauer (Sekunden):"))
        self.timestamp_duration_spin = QSpinBox()
        self.timestamp_duration_spin.setMinimum(1)
        self.timestamp_duration_spin.setMaximum(10)
        timestamp_layout.addWidget(self.timestamp_duration_spin)
        timestamp_layout.addStretch()
        capture_layout.addLayout(timestamp_layout)
        
        capture_group.setLayout(capture_layout)
        scroll_layout.addWidget(capture_group)
        
        # UI-Einstellungen
        ui_group = QGroupBox("Benutzeroberfläche")
        ui_layout = QHBoxLayout()
        ui_layout.addWidget(QLabel("Preview FPS:"))
        self.preview_fps_spin = QSpinBox()
        self.preview_fps_spin.setMinimum(1)
        self.preview_fps_spin.setMaximum(30)
        ui_layout.addWidget(self.preview_fps_spin)
        ui_layout.addStretch()
        ui_group.setLayout(ui_layout)
        scroll_layout.addWidget(ui_group)
        
        # Upscaling
        upscaling_group = QGroupBox("Upscaling")
        upscaling_layout = QHBoxLayout()
        upscaling_layout.addWidget(QLabel("Standard-Profil:"))
        self.profile_combo = QComboBox()
        profiles = self.config.get("upscaling.profiles", {})
        for profile_name in profiles.keys():
            self.profile_combo.addItem(profile_name)
        upscaling_layout.addWidget(self.profile_combo)
        upscaling_group.setLayout(upscaling_layout)
        scroll_layout.addWidget(upscaling_group)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        container_layout.addWidget(scroll)
        
        # Button Box
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        container_layout.addWidget(button_box)
    
    def _load_settings(self):
        """Lädt aktuelle Einstellungen in die UI"""
        # Pfade
        plex_root = self.config.get_plex_movies_root()
        self.plex_movies_edit.setText(str(plex_root))
        
        dv_root = self.config.get_dv_import_root()
        self.dv_import_edit.setText(str(dv_root))
        
        # ffmpeg: Zeige nur wenn explizit gesetzt, sonst leer
        ffmpeg_path_config = self.config.get("paths.ffmpeg_path", "")
        if ffmpeg_path_config and ffmpeg_path_config.strip():
            self.ffmpeg_edit.setText(ffmpeg_path_config)
        else:
            self.ffmpeg_edit.setText("")
        
        # RealESRGAN: Zeige nur wenn explizit gesetzt, sonst leer
        realesrgan_path_config = self.config.get("paths.realesrgan_path", "")
        if realesrgan_path_config and realesrgan_path_config.strip():
            self.realesrgan_edit.setText(realesrgan_path_config)
        else:
            self.realesrgan_edit.setText("")
        
        # Device
        firewire_device = self.config.get("device.firewire_device", "")
        self.firewire_edit.setText(firewire_device)
        
        # Capture
        self.auto_postprocess_checkbox.setChecked(
            self.config.get("capture.auto_postprocess", False)
        )
        self.auto_upscale_checkbox.setChecked(
            self.config.get("capture.auto_upscale", True)
        )
        self.auto_export_checkbox.setChecked(
            self.config.get("capture.auto_export", False)
        )
        self.auto_rewind_play_checkbox.setChecked(
            self.config.get("capture.auto_rewind_play", True)
        )
        self.timestamp_overlay_checkbox.setChecked(
            self.config.get("capture.timestamp_overlay", True)
        )
        self.timestamp_duration_spin.setValue(
            self.config.get("capture.timestamp_duration", 4)
        )
        
        # UI
        self.preview_fps_spin.setValue(
            self.config.get("ui.preview_fps", 10)
        )
        
        # Upscaling
        default_profile = self.config.get("upscaling.default_profile", "realesrgan_2x")
        index = self.profile_combo.findText(default_profile)
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)
    
    def _save_settings(self):
        """Speichert Einstellungen aus der UI"""
        # Pfade
        self.config.set("paths.plex_movies_root", self.plex_movies_edit.text())
        self.config.set("paths.dv_import_root", self.dv_import_edit.text())
        
        # ffmpeg: Leer = System-PATH verwenden
        ffmpeg_text = self.ffmpeg_edit.text().strip()
        self.config.set("paths.ffmpeg_path", ffmpeg_text if ffmpeg_text else "")
        
        # RealESRGAN: Leer = System-PATH verwenden
        realesrgan_text = self.realesrgan_edit.text().strip()
        self.config.set("paths.realesrgan_path", realesrgan_text if realesrgan_text else "")
        
        # Device
        firewire_text = self.firewire_edit.text().strip()
        self.config.set("device.firewire_device", firewire_text if firewire_text else "")
        
        # Capture
        self.config.set("capture.auto_postprocess", self.auto_postprocess_checkbox.isChecked())
        self.config.set("capture.auto_upscale", self.auto_upscale_checkbox.isChecked())
        self.config.set("capture.auto_export", self.auto_export_checkbox.isChecked())
        self.config.set("capture.auto_rewind_play", self.auto_rewind_play_checkbox.isChecked())
        self.config.set("capture.timestamp_overlay", self.timestamp_overlay_checkbox.isChecked())
        self.config.set("capture.timestamp_duration", self.timestamp_duration_spin.value())
        
        # UI
        self.config.set("ui.preview_fps", self.preview_fps_spin.value())
        
        # Upscaling
        self.config.set("upscaling.default_profile", self.profile_combo.currentText())
        
        # Speichere Config
        self.config.save_config()
    
    def accept(self):
        """Überschreibt accept() um Settings zu speichern"""
        self._save_settings()
        QMessageBox.information(self, "Einstellungen", "Einstellungen wurden gespeichert.")
        super().accept()
    
    def _on_browse_plex_movies(self):
        """Öffnet Ordner-Dialog für Plex Movies"""
        current_path = self.plex_movies_edit.text()
        folder = QFileDialog.getExistingDirectory(
            self,
            "Plex Movies Ordner wählen",
            current_path if current_path else ""
        )
        if folder:
            self.plex_movies_edit.setText(folder)
    
    def _on_browse_dv_import(self):
        """Öffnet Ordner-Dialog für DV Import Root"""
        current_path = self.dv_import_edit.text()
        folder = QFileDialog.getExistingDirectory(
            self,
            "DV Import Root Ordner wählen",
            current_path if current_path else ""
        )
        if folder:
            self.dv_import_edit.setText(folder)
    
    def _on_browse_ffmpeg(self):
        """Öffnet Datei-Dialog für ffmpeg"""
        current_path = self.ffmpeg_edit.text()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "ffmpeg auswählen",
            current_path if current_path else "",
            "Executable (*);;All Files (*)"
        )
        if file_path:
            self.ffmpeg_edit.setText(file_path)
    
    def _on_browse_realesrgan(self):
        """Öffnet Datei-Dialog für RealESRGAN"""
        current_path = self.realesrgan_edit.text()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "inference_realesrgan_video.py auswählen",
            current_path if current_path else "",
            "Python Files (*.py);;All Files (*)"
        )
        if file_path:
            self.realesrgan_edit.setText(file_path)


def main():
    """Hauptfunktion"""
    # Prüfe und lade fehlende Komponenten beim Start
    try:
        from .download_manager import check_and_download_on_startup
        from pathlib import Path
        base_dir = Path(__file__).parent.parent
        check_and_download_on_startup(base_dir, auto_download=False)
    except ImportError:
        # Fallback wenn download_manager nicht verfügbar
        pass
    except Exception as e:
        # Fehler beim Download-Manager sollten die Anwendung nicht blockieren
        logging.warning(f"Fehler beim Prüfen der Komponenten: {e}")
    
    app = QApplication(sys.argv)
    app.setApplicationName("DV2Plex")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

