"""
Poster-Generierung Engine für die Erstellung von Plex Movie Posters
Basierend auf HTML-Template und Playwright-Rendering
"""

import os
import re
import subprocess
import tempfile
import warnings
import base64
import io
from pathlib import Path
import logging
from typing import Optional, Callable, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from sklearn.cluster import KMeans
from rembg import remove

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Unterdrücke Performance-Warnungen von rembg
warnings.filterwarnings("ignore", category=UserWarning, message=".*Cholesky.*")
warnings.filterwarnings("ignore", category=UserWarning, message=".*PERFORMANCE WARNING.*")


logger = logging.getLogger(__name__)


# ----------------------------
# ffmpeg helpers
# ----------------------------
def run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed:\n{' '.join(cmd)}\n\n{p.stderr}")


def probe_duration_seconds(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0 or not p.stdout.strip():
        raise RuntimeError("ffprobe konnte die Videodauer nicht lesen. Ist ffmpeg/ffprobe installiert und im PATH?")
    return float(p.stdout.strip())


def probe_video_meta(video_path: str) -> dict:
    """
    Liest Video-Metadaten via ffprobe aus (Dauer, Auflösung, FPS, Codec).
    Gibt ein Dict zurück mit keys: duration, width, height, fps, codec, interlaced
    """
    import json
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,codec_name,field_order",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        return {}
    
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {}
    
    meta = {}
    
    # Duration
    if "format" in data and "duration" in data["format"]:
        dur = float(data["format"]["duration"])
        h = int(dur // 3600)
        m = int((dur % 3600) // 60)
        s = int(dur % 60)
        meta["duration"] = f"{h:02d}:{m:02d}:{s:02d}"
    
    # Stream info
    if "streams" in data and len(data["streams"]) > 0:
        stream = data["streams"][0]
        meta["width"] = stream.get("width", 0)
        meta["height"] = stream.get("height", 0)
        meta["codec"] = stream.get("codec_name", "").upper()
        
        # FPS
        fps_str = stream.get("r_frame_rate", "25/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = round(int(num) / int(den)) if int(den) != 0 else 25
        else:
            fps = round(float(fps_str))
        meta["fps"] = fps
        
        # Interlaced?
        field_order = stream.get("field_order", "progressive")
        meta["interlaced"] = field_order not in ["progressive", "unknown", ""]
    
    return meta


def extract_frame(video_path: str, t_sec: float, out_png: str) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{t_sec:.3f}",
        "-i", video_path,
        "-frames:v", "1",
        "-vf", "yadif=1:-1:0,scale=1600:-1",  # Deinterlace + Scale
        out_png
    ]
    run(cmd)


def pick_best_frame(video_path: str, samples: int = 18, start_skip: float = 0.08, end_skip: float = 0.08) -> Image.Image:
    dur = probe_duration_seconds(video_path)
    start = dur * start_skip
    end = dur * (1 - end_skip)
    if end <= start:
        start, end = 0, dur

    times = np.linspace(start, end, samples)
    best_score = -1.0
    best_img = None

    with tempfile.TemporaryDirectory() as td:
        for t in times:
            fp = os.path.join(td, f"f_{t:.3f}.png")
            extract_frame(video_path, float(t), fp)

            bgr = cv2.imread(fp, cv2.IMREAD_COLOR)
            if bgr is None:
                continue

            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

            sharp = cv2.Laplacian(gray, cv2.CV_64F).var()
            edges = cv2.Canny(gray, 60, 140)
            edge_density = edges.mean() / 255.0
            # Gesichts-Score: bevorzugt größtes Gesicht, das mittig liegt
            faces = detect_faces(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
            face_score = 0.0
            if faces:
                fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                face_area = (fw * fh) / (bgr.shape[0] * bgr.shape[1])
                cx = fx + fw / 2.0
                cy = fy + fh / 2.0
                dx = abs(cx - bgr.shape[1] / 2.0) / (bgr.shape[1] / 2.0)
                dy = abs(cy - bgr.shape[0] / 2.0) / (bgr.shape[0] / 2.0)
                center_bonus = 1.0 - (dx * 0.7 + dy * 0.3)
                face_score = face_area * max(0.0, center_bonus)

            # Helligkeit: zu dunkle Frames abwerten
            brightness = gray.mean() / 255.0
            dark_penalty = 0.6 if brightness < 0.20 else 1.0

            score = (sharp * (1.15 - min(edge_density, 1.0))) * dark_penalty + (face_score * 1500.0)
            if score > best_score:
                best_score = score
                best_img = Image.open(fp).convert("RGB")

    if best_img is None:
        raise RuntimeError("Konnte keinen Frame extrahieren.")
    return best_img


# ----------------------------
# Face detection
# ----------------------------
def detect_faces(frame_rgb: Image.Image) -> list[tuple[int, int, int, int]]:
    """
    Erkennt Gesichter im Frame mit Haar Cascades (offline, keine Cloud).
    Gibt Liste von (x, y, w, h) Bounding-Boxen zurück.
    """
    bgr = cv2.cvtColor(np.array(frame_rgb), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    
    # Lade Frontalface-Cascade (Standard, funktioniert für die meisten Fälle)
    face_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    face_cascade = cv2.CascadeClassifier(face_cascade_path)
    
    if face_cascade.empty():
        return []
    
    # Erkenne Gesichter (scaleFactor=1.1, minNeighbors=5 für bessere Qualität)
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(30, 30),
        flags=cv2.CASCADE_SCALE_IMAGE
    )
    
    # Optional: Profil-Cascade für seitliche Gesichter (wenn Frontalface nichts findet)
    if len(faces) == 0:
        profile_cascade_path = cv2.data.haarcascades + 'haarcascade_profileface.xml'
        profile_cascade = cv2.CascadeClassifier(profile_cascade_path)
        if not profile_cascade.empty():
            faces = profile_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30),
                flags=cv2.CASCADE_SCALE_IMAGE
            )
    
    return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]


def extract_year_from_title(title: str, year: str | None) -> tuple[str, str | None]:
    """
    Holt ein Jahr aus dem Titel, wenn es in Klammern steht, z.B. "Faschingsumzug (2003)".
    Gibt (bereinigter Titel, Jahr) zurück. Wenn year bereits gesetzt ist, bleibt es erhalten.
    """
    if year and year.strip():
        return title, year
    m = re.search(r"\((\d{4})\)", title)
    if m:
        found_year = m.group(1)
        clean_title = re.sub(r"\s*\(\d{4}\)\s*", "", title).strip()
        return clean_title, found_year
    return title, year


# ----------------------------
# Color + cutout
# ----------------------------
def ai_cutout(img: Image.Image) -> Image.Image:
    """
    KI-Freistellung mit rembg (U²-Net), läuft lokal auf CPU.
    """
    rgba = remove(
        img,
        alpha_matting=True,
        alpha_matting_foreground_threshold=235,
        alpha_matting_background_threshold=15,
        alpha_matting_erode_size=8,
    )
    return rgba


def stylize_subject(rgba: Image.Image) -> Image.Image:
    arr = np.array(rgba).astype(np.float32)
    rgb = arr[..., :3]
    a = arr[..., 3:4] / 255.0

    gray = (0.299*rgb[..., 0] + 0.587*rgb[..., 1] + 0.114*rgb[..., 2])[..., None]
    rgb2 = rgb * 0.55 + gray * 0.45
    rgb2 = (rgb2 - 128) * 1.15 + 128
    rgb2 = np.clip(rgb2, 0, 255)

    out = np.dstack([rgb2, a*255.0]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def poster_grade(rgba: Image.Image) -> Image.Image:
    """Warmer, kontrastreicher Look für das Motiv."""
    arr = np.array(rgba).astype(np.float32)
    rgb = arr[..., :3]
    a = arr[..., 3:4]

    # Warmes Licht
    rgb[..., 0] *= 1.05
    rgb[..., 1] *= 1.02
    rgb[..., 2] *= 0.97

    # Leichte S-Kurve
    rgb = (rgb - 128) * 1.25 + 128

    # Schwarzwert anheben
    rgb = np.maximum(rgb, 18)

    rgb = np.clip(rgb, 0, 255)
    out = np.dstack([rgb, a]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def refine_alpha(rgba: Image.Image, feather: int = 3, shrink: int = 1) -> Image.Image:
    """Weicht die Alpha-Kante auf und schrumpft sie leicht (Defringe)."""
    arr = np.array(rgba).copy()
    a = arr[:, :, 3]

    if shrink > 0:
        k = shrink * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        a = cv2.erode(a, kernel, iterations=1)

    if feather > 0:
        k = feather * 2 + 1
        a = cv2.GaussianBlur(a, (k, k), 0)

    arr[:, :, 3] = a
    return Image.fromarray(arr, "RGBA")


def crop_to_alpha(rgba: Image.Image, pad: int = 20) -> Image.Image:
    """Croppt ein RGBA-Bild auf die nicht-transparente Fläche."""
    arr = np.array(rgba)
    alpha = arr[:, :, 3]
    ys, xs = np.where(alpha > 10)
    if len(xs) == 0 or len(ys) == 0:
        return rgba
    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(rgba.width - 1, x1 + pad)
    y1 = min(rgba.height - 1, y1 + pad)
    return rgba.crop((x0, y0, x1 + 1, y1 + 1))


def cutout_is_sane(rgba: Image.Image, faces: list[tuple[int, int, int, int]] | None = None) -> bool:
    """
    Reject kaputte Cutouts (Portrait-Gate).
    Filtert Fransen/Artefakte, abgeschnittene Motive und typische Streifen.
    """
    a = np.array(rgba)[..., 3]
    H, W = a.shape

    mask = (a > 32).astype(np.uint8)
    fill = mask.mean()
    if fill < 0.05:
        return False

    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num <= 1:
        return False

    areas = stats[1:, 4]
    big = (areas > 0.01 * W * H).sum()
    if big >= 3:
        return False

    idx = 1 + np.argmax(areas)
    x, y, w, h, area = stats[idx]
    area_frac = area / float(W * H)
    if area_frac < 0.06:
        return False

    # Randkontakt -> meist abgeschnitten
    pad = int(0.02 * min(W, H))
    touches = (x <= pad) or (y <= pad) or (x + w >= W - pad) or (y + h >= H - pad)
    if touches:
        return False

    # Streifen-/Mast-Heuristiken
    if (w / W) < 0.20 and (h / H) > 0.50:
        return False
    if min(w, h) / max(w, h) < 0.12:
        return False

    # Hauptgesicht muss in der größten Komponente liegen
    if faces:
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        face_ok = (fx >= x and fy >= y and (fx + fw) <= (x + w) and (fy + fh) <= (y + h))
        if not face_ok:
            return False
        if (fw * fh) / float(W * H) < 0.02:
            return False

    return True


def add_shadow(rgba: Image.Image, blur: int = 10, offset=(0, 18), opacity: int = 90) -> Image.Image:
    """Fügt einen weichen Schatten unter das Motiv hinzu, um es zu erden."""
    arr = np.array(rgba)
    alpha = arr[:, :, 3]

    shadow = np.zeros_like(alpha)
    shadow[alpha > 10] = opacity
    shadow = cv2.GaussianBlur(shadow, (blur * 2 + 1, blur * 2 + 1), 0)

    sh = np.zeros((rgba.height, rgba.width, 4), dtype=np.uint8)
    sh[:, :, 3] = shadow
    shadow_img = Image.fromarray(sh, "RGBA")

    out_w = rgba.width + abs(offset[0]) + blur * 2
    out_h = rgba.height + abs(offset[1]) + blur * 2
    out = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    out.paste(shadow_img, (blur + max(offset[0], 0), blur + max(offset[1], 0)), shadow_img)
    out.paste(rgba, (blur, blur), rgba)
    return out


def add_film_grain(img: Image.Image, strength: int = 6) -> Image.Image:
    """Fügt feines Filmkorn hinzu, um den Druck-Look zu unterstützen."""
    arr = np.array(img).astype(np.float32)
    noise = np.random.normal(0, strength, arr.shape[:2]).astype(np.float32)
    arr[..., 0] += noise
    arr[..., 1] += noise
    arr[..., 2] += noise
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def add_paper_vignette(img: Image.Image, strength: float = 0.16) -> Image.Image:
    """Subtile Rand-Vignette für Druck-Look."""
    W, H = img.size
    xv = np.linspace(-1, 1, W)
    yv = np.linspace(-1, 1, H)
    xx, yy = np.meshgrid(xv, yv)
    rr = np.sqrt(xx * xx + yy * yy)
    mask = np.clip((rr - 0.2) / 0.9, 0, 1)
    mask = (mask * 255 * strength).astype(np.uint8)

    arr = np.array(img).astype(np.int16)
    arr[..., 0] = np.clip(arr[..., 0] - mask, 0, 255)
    arr[..., 1] = np.clip(arr[..., 1] - mask, 0, 255)
    arr[..., 2] = np.clip(arr[..., 2] - mask, 0, 255)
    return Image.fromarray(arr.astype(np.uint8))


def cover_resize(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize+Crop wie CSS background-size: cover"""
    w, h = img.size
    s = max(target_w / w, target_h / h)
    nw, nh = int(w * s), int(h * s)
    r = img.resize((nw, nh), Image.LANCZOS)
    x0 = (nw - target_w) // 2
    y0 = (nh - target_h) // 2
    return r.crop((x0, y0, x0 + target_w, y0 + target_h))


def make_no(year: str | None) -> str:
    """Erstellt Nummer aus Jahr (z.B. '2003' -> 'NO. 03')."""
    if year and year.isdigit():
        return f"NO. {year[-2:]}"
    return "NO. 03"


def make_poster_from_html(
    frame_rgb: Image.Image, 
    title: str, 
    subtitle: str | None, 
    year: str | None, 
    out_path: str, 
    video_path: str | None = None, 
    size=(3000, 4500),
    template_path: Optional[Path] = None
):
    """
    Erstellt Poster aus HTML-Template: verarbeitet Bild, füllt Template, rendert zu Bild, 
    wendet Grain und Vintage-Effekte an.
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("playwright nicht installiert. Installiere mit: pip install playwright && playwright install chromium")
    
    W, H = size
    
    # 1. Bild verarbeiten (AUTO: Cutout nur wenn sinnvoll)
    faces = detect_faces(frame_rgb)
    use_cutout = False
    cut = None

    # Gruppen => kein Cutout
    if len(faces) < 2:
        try:
            rgba = ai_cutout(frame_rgb)
            rgba = refine_alpha(rgba, feather=3, shrink=1)

            if faces or cutout_is_sane(rgba, faces=faces):
                rgba = crop_to_alpha(rgba, pad=40)
                cut = rgba
                use_cutout = True
            else:
                use_cutout = False
        except Exception:
            use_cutout = False

    block_h = int(H * 0.48)

    if use_cutout:
        cut = stylize_subject(cut)
        cut = poster_grade(cut)
        cut = add_shadow(cut, blur=9, offset=(0, 16), opacity=70)

        # Skalierung wie gehabt
        if faces:
            face_scores = [(w * h, (x, y, w, h)) for (x, y, w, h) in faces]
            face_scores.sort(reverse=True, key=lambda x: x[0])
            _, (fx, fy, fw, fh) = face_scores[0]
            target_face_h = int(block_h * 0.50)
            scale = (target_face_h / fh)
            cut = cut.resize((int(cut.width * scale), int(cut.height * scale)), Image.LANCZOS)
        else:
            target_h = int(block_h * 0.82)
            scale = target_h / cut.height
            cut = cut.resize((int(cut.width * scale), int(cut.height * scale)), Image.LANCZOS)

        subject_img = cut

    else:
        # NO-CUTOUT fallback: full frame cover im Bildblock
        block_w = int(W * 0.82)
        block_hh = block_h
        photo = cover_resize(frame_rgb, block_w, block_hh).convert("RGB")
        subject_img = photo

    # Bild als base64 für HTML
    img_buffer = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    subject_img.save(img_buffer.name, 'PNG')
    img_buffer.close()
    
    with open(img_buffer.name, 'rb') as f:
        img_data = base64.b64encode(f.read()).decode('utf-8')
    os.unlink(img_buffer.name)
    
    # 2. Meta-Daten vorbereiten
    meta_lines = []
    if video_path:
        try:
            vmeta = probe_video_meta(video_path)
            parts = []
            codec = vmeta.get("codec", "").upper()
            if codec in ["H264", "AVC"]:
                codec = "H.264"
            elif codec in ["HEVC", "H265"]:
                codec = "H.265"
            elif codec == "DVVIDEO":
                codec = "DV"
            if codec:
                parts.append(codec)
            if vmeta.get("width") and vmeta.get("height"):
                res = f"{vmeta['width']}×{vmeta['height']}"
                if vmeta.get("interlaced"):
                    res += "i"
                parts.append(res)
            if vmeta.get("fps"):
                parts.append(f"{vmeta['fps']}fps")
            if parts:
                meta_lines.append(" · ".join(parts))
            if vmeta.get("duration"):
                meta_lines.append(vmeta["duration"])
        except Exception:
            pass
    
    if not meta_lines:
        meta_lines = ["DIGITIZED FROM TAPE", "01:00:00"]
    
    meta_lines = meta_lines[:2] + [make_no(year)]
    
    # 3. HTML-Template laden und Variablen ersetzen
    if template_path is None:
        template_path = Path(__file__).parent / "resources" / "poster_template.html"
    
    if not template_path.exists():
        raise FileNotFoundError(f"Template nicht gefunden: {template_path}")
    
    with open(template_path, 'r', encoding='utf-8') as f:
        html = f.read()
    
    # Titel umbrechen (intelligent bei " u. ", " mit ", etc.)
    title_html = title
    separators = [" u. ", " mit ", " & ", " und "]
    for sep in separators:
        if sep in title:
            parts = title.split(sep, 1)
            title_html = f"{parts[0]}<br>{sep}{parts[1]}"
            break
    else:
        # Fallback: bei Leerzeichen umbrechen
        words = title.split()
        if len(words) > 1:
            mid = len(words) // 2
            title_html = f"{' '.join(words[:mid])}<br>{' '.join(words[mid:])}"
    
    # Platzhalter ersetzen
    html = html.replace("__TITLE__", title_html)
    html = html.replace("__YEAR__", year if year else "2003")

    # Meta-Zeilen einsetzen (auffüllen auf 3 Zeilen)
    meta_filled = meta_lines + [""] * (3 - len(meta_lines))
    html = html.replace("__META1__", meta_filled[0] if len(meta_filled) > 0 else "")
    html = html.replace("__META2__", meta_filled[1] if len(meta_filled) > 1 else "")
    html = html.replace("__META3__", meta_filled[2] if len(meta_filled) > 2 else "")
    
    # Bild einfügen
    img_tag = f'<img src="data:image/png;base64,{img_data}" alt="Motiv" class="subject-image">'
    html = html.replace('<!-- Füge hier dein Bild ein: -->\n                <!-- <img src="dein-bild.png" alt="Motiv" class="subject-image"> -->', img_tag)
    
    # 4. HTML zu Bild rendern
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as tmp_html:
        tmp_html.write(html)
        tmp_html_path = tmp_html.name
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': W, 'height': H})
            page.goto(f'file://{tmp_html_path}')
            page.wait_for_timeout(1000)  # Warte auf Fonts/CSS
            
            # Screenshot nur vom Poster-Element (nicht vom ganzen Body)
            poster_element = page.locator('.poster')
            screenshot = poster_element.screenshot(type='png')
            browser.close()
        
        # 5. Grain und Vintage-Effekte anwenden
        canvas = Image.open(io.BytesIO(screenshot))
        
        # Stelle sicher, dass die Größe stimmt
        if canvas.size != (W, H):
            canvas = canvas.resize((W, H), Image.LANCZOS)
        
        canvas = add_paper_vignette(canvas, strength=0.16)
        canvas = add_film_grain(canvas, strength=5)
        canvas.save(out_path, quality=95)
    
    finally:
        if os.path.exists(tmp_html_path):
            os.unlink(tmp_html_path)


class PosterGenerationEngine:
    """Verwaltet die Generierung von Movie Posters mit HTML-Template"""
    
    def __init__(
        self,
        template_path: Optional[Path] = None,
        log_callback: Optional[Callable] = None
    ):
        """
        Initialisiert die Poster-Generierung Engine
        
        Args:
            template_path: Pfad zum HTML-Template (Standard: resources/poster_template.html)
            log_callback: Optionaler Callback für Log-Nachrichten
        """
        self.template_path = template_path
        self.log_callback = log_callback or (lambda msg: logger.info(msg))
    
    def generate_poster(
        self,
        video_path: Path,
        title: str,
        year: Optional[str] = None,
        output_path: Optional[Path] = None,
        size: Tuple[int, int] = (3000, 4500)
    ) -> Optional[Path]:
        """
        Generiert ein Poster aus einem Video
        
        Args:
            video_path: Pfad zum Video
            title: Filmtitel
            year: Jahr (optional)
            output_path: Ausgabepfad (Standard: poster.jpg im Video-Ordner)
            size: Poster-Größe (width, height)
            
        Returns:
            Pfad zum generierten Poster oder None bei Fehler
        """
        if not video_path.exists():
            self.log(f"Video nicht gefunden: {video_path}")
            return None
        
        try:
            # Best Frame extrahieren
            self.log(f"Extrahiere besten Frame aus: {video_path.name}")
            frame = pick_best_frame(str(video_path), samples=18)
            
            # Titel und Jahr aufräumen
            title, year = extract_year_from_title(title, year)
            
            # Output-Pfad bestimmen
            if output_path is None:
                output_path = video_path.parent / "poster.jpg"
            
            # Poster generieren
            self.log(f"Generiere Poster: {title} ({year})")
            make_poster_from_html(
                frame,
                title,
                None,  # subtitle
                year,
                str(output_path),
                str(video_path),
                size=size,
                template_path=self.template_path
            )
            
            self.log(f"Poster erfolgreich generiert: {output_path}")
            return output_path
            
        except Exception as e:
            self.log(f"Fehler bei Poster-Generierung: {e}")
            import traceback
            self.log(traceback.format_exc())
            return None
    
    def log(self, message: str):
        """Loggt eine Nachricht"""
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

