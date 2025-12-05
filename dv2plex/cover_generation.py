"""
Cover-Generierung Engine für die Erstellung von Plex Movie Covers mit Stable Diffusion
"""

import torch
from pathlib import Path
from typing import Optional, Callable
import logging
from PIL import Image

try:
    from diffusers import StableDiffusionImg2ImgPipeline
    from diffusers.utils import load_image
    DIFFUSERS_AVAILABLE = True
except ImportError:
    DIFFUSERS_AVAILABLE = False


class CoverGenerationEngine:
    """Verwaltet die Generierung von Movie Covers mit Stable Diffusion"""
    
    DEFAULT_PROMPT = "cinematic movie poster, dramatic lighting, vintage film look, high detail, professional photography"
    DEFAULT_SIZE = (1000, 1500)  # Plex Standard Poster-Größe
    DEFAULT_STRENGTH = 0.6
    DEFAULT_GUIDANCE_SCALE = 8.0
    
    def __init__(
        self,
        model_id: str = "runwayml/stable-diffusion-v1-5",
        log_callback: Optional[Callable] = None,
        device: Optional[str] = None
    ):
        """
        Initialisiert die Cover-Generierung Engine
        
        Args:
            model_id: Hugging Face Modell-ID für Stable Diffusion
            log_callback: Optionaler Callback für Log-Nachrichten
            device: Device ("cuda", "cpu", oder None für Auto-Detection)
        """
        if not DIFFUSERS_AVAILABLE:
            raise ImportError(
                "diffusers ist nicht installiert. "
                "Bitte installieren Sie es mit: pip install diffusers transformers accelerate"
            )
        
        self.model_id = model_id
        self.log_callback = log_callback
        self.logger = logging.getLogger(__name__)
        
        # Device-Auswahl
        if device is None:
            if torch.cuda.is_available():
                self.device = "cuda"
                self.dtype = torch.float16  # FP16 für bessere Performance
            else:
                self.device = "cpu"
                self.dtype = torch.float32
        else:
            self.device = device
            self.dtype = torch.float16 if device == "cuda" else torch.float32
        
        self.pipeline = None
        self.log(f"Initialisiere Cover-Generierung Engine auf {self.device}")
    
    def _load_pipeline(self):
        """Lädt die Stable Diffusion Pipeline (lazy loading)"""
        if self.pipeline is not None:
            return
        
        try:
            self.log(f"Lade Stable Diffusion Modell: {self.model_id}")
            self.log("Dies kann beim ersten Mal einige Minuten dauern...")
            
            self.pipeline = StableDiffusionImg2ImgPipeline.from_pretrained(
                self.model_id,
                torch_dtype=self.dtype,
                safety_checker=None,  # Optional: Deaktivieren für schnellere Generierung
                requires_safety_checker=False
            )
            self.pipeline = self.pipeline.to(self.device)
            
            # Optimierungen für bessere Performance
            if self.device == "cuda":
                self.pipeline.enable_attention_slicing()
                # Optional: enable_memory_efficient_attention() wenn verfügbar
                try:
                    self.pipeline.enable_xformers_memory_efficient_attention()
                except Exception:
                    pass  # xformers nicht verfügbar, ist ok
            
            self.log("Modell erfolgreich geladen")
            
        except Exception as e:
            self.log(f"Fehler beim Laden des Modells: {e}")
            raise
    
    def _prepare_input_image(self, image_path: Path, target_size: tuple) -> Image.Image:
        """
        Bereitet das Eingabebild vor (Resize auf Zielgröße)
        
        Args:
            image_path: Pfad zum Eingabebild
            target_size: Zielgröße (width, height)
            
        Returns:
            Vorbereitetes PIL Image
        """
        image = Image.open(image_path).convert("RGB")
        
        # Resize mit Aspect Ratio Preservation
        image.thumbnail(target_size, Image.Resampling.LANCZOS)
        
        # Erstelle neues Bild mit exakter Größe und zentriere das Original
        new_image = Image.new("RGB", target_size, (0, 0, 0))
        paste_x = (target_size[0] - image.width) // 2
        paste_y = (target_size[1] - image.height) // 2
        new_image.paste(image, (paste_x, paste_y))
        
        return new_image
    
    def generate_cover(
        self,
        input_image: Path,
        output_path: Path,
        prompt: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        strength: float = None,
        guidance_scale: float = None,
        num_inference_steps: int = 50,
        output_size: Optional[tuple] = None
    ) -> Optional[Path]:
        """
        Generiert ein Movie Cover aus einem Frame
        
        Args:
            input_image: Pfad zum Eingabebild (Frame)
            output_path: Pfad für das generierte Cover
            prompt: Text-Prompt für die Generierung (Standard wird verwendet wenn None)
            negative_prompt: Negativer Prompt (was vermieden werden soll)
            strength: Wie stark das Originalbild verändert wird (0.0-1.0, Standard: 0.6)
            guidance_scale: Guidance Scale (Standard: 8.0)
            num_inference_steps: Anzahl der Inference-Schritte (Standard: 50)
            output_size: Ausgabegröße (width, height), Standard: (1000, 1500)
            
        Returns:
            Pfad zum generierten Cover oder None bei Fehler
        """
        if not input_image.exists():
            self.log(f"Eingabebild nicht gefunden: {input_image}")
            return None
        
        # Lade Pipeline falls noch nicht geladen
        self._load_pipeline()
        
        # Standardwerte
        if prompt is None:
            prompt = self.DEFAULT_PROMPT
        if strength is None:
            strength = self.DEFAULT_STRENGTH
        if guidance_scale is None:
            guidance_scale = self.DEFAULT_GUIDANCE_SCALE
        if output_size is None:
            output_size = self.DEFAULT_SIZE
        
        if negative_prompt is None:
            negative_prompt = "blurry, low quality, distorted, watermark, text"
        
        try:
            self.log(f"Generiere Cover aus: {input_image.name}")
            self.log(f"Prompt: {prompt}")
            self.log(f"Strength: {strength}, Guidance Scale: {guidance_scale}")
            
            # Bereite Eingabebild vor
            init_image = self._prepare_input_image(input_image, output_size)
            
            # Generiere Cover
            result = self.pipeline(
                prompt=prompt,
                image=init_image,
                negative_prompt=negative_prompt,
                strength=strength,
                guidance_scale=guidance_scale,
                num_inference_steps=num_inference_steps
            )
            
            # Speichere Ergebnis
            output_image = result.images[0]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_image.save(output_path, quality=95)
            
            self.log(f"Cover erfolgreich generiert: {output_path}")
            return output_path
            
        except Exception as e:
            self.log(f"Fehler bei Cover-Generierung: {e}")
            import traceback
            self.log(traceback.format_exc())
            return None
    
    def log(self, message: str):
        """Loggt eine Nachricht"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
