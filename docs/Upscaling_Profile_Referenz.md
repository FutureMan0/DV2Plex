# Upscaling-Profile Referenz

## Übersicht der verfügbaren Profile

Diese Tabelle dokumentiert alle verfügbaren Upscaling-Profile mit ihren Parametern, Verwendungszwecken und Performance-Charakteristika.

---

## RealESRGAN-Profile

### RealESRGAN 4x HQ (Höchste Qualität)

**Verwendungszweck:** Beste Qualität für wichtige Aufnahmen, Zeit spielt keine Rolle

| Parameter | Wert | Beschreibung |
|-----------|------|--------------|
| Backend | `realesrgan` | RealESRGAN-Engine |
| Scale Factor | `4` | 4x Upscaling |
| Model | `RealESRGAN_x4plus` | RealESRGAN x4plus Modell (höchste Qualität) |
| Encoder | `libx264rgb` | RGB-Encoder für bessere Farbqualität |
| CRF | `17` | Sehr hohe Qualität (18-23 ist Standard) |
| Preset | `veryslow` | Langsamste, aber beste Kompression |
| Tune | `film` | Optimiert für Filmmaterial |

**Geschätzte Verarbeitungszeit:** ~10-20 Minuten pro Minute Video (abhängig von GPU)
**Empfohlen für:** Wichtige Familienaufnahmen, Archivmaterial

---

### RealESRGAN 4x Standard

**Verwendungszweck:** Gute Balance zwischen Qualität und Geschwindigkeit

| Parameter | Wert | Beschreibung |
|-----------|------|--------------|
| Backend | `realesrgan` | RealESRGAN-Engine |
| Scale Factor | `4` | 4x Upscaling |
| Model | `RealESRGAN_x4plus` | RealESRGAN x4plus Modell |
| Face Enhance | `false` | Keine Gesichtsverbesserung |
| Encoder | `libx264` | Standard H.264-Encoder |
| CRF | `18` | Hohe Qualität |
| Preset | `slow` | Gute Balance |
| Tune | `film` | Optimiert für Filmmaterial |

**Geschätzte Verarbeitungszeit:** ~5-10 Minuten pro Minute Video
**Empfohlen für:** Standard-Digitalisierungen

---

### RealESRGAN 4x Fast

**Verwendungszweck:** Schnelle Verarbeitung, akzeptable Qualität

| Parameter | Wert | Beschreibung |
|-----------|------|--------------|
| Backend | `realesrgan` | RealESRGAN-Engine |
| Scale Factor | `4` | 4x Upscaling |
| Model | `RealESRGAN_x4plus` | RealESRGAN x4plus Modell |
| Face Enhance | `false` | Keine Gesichtsverbesserung |
| Encoder | `libx264` | Standard H.264-Encoder (schneller) |
| CRF | `20` | Gute Qualität |
| Preset | `medium` | Schnellere Kompression |
| Tune | `film` | Optimiert für Filmmaterial |

**Geschätzte Verarbeitungszeit:** ~3-5 Minuten pro Minute Video
**Empfohlen für:** Schnelle Durchsicht, Testläufe

---

### RealESRGAN 2x

**Verwendungszweck:** 2x Upscaling (schneller als 4x)

| Parameter | Wert | Beschreibung |
|-----------|------|--------------|
| Backend | `realesrgan` | RealESRGAN-Engine |
| Scale Factor | `2` | 2x Upscaling |
| Model | `RealESRGAN_x2plus` | RealESRGAN x2plus Modell |
| Face Enhance | `false` | Keine Gesichtsverbesserung |
| Encoder | `libx264` | Standard H.264-Encoder |
| CRF | `18` | Hohe Qualität |
| Preset | `slow` | Gute Balance |
| Tune | `film` | Optimiert für Filmmaterial |

**Geschätzte Verarbeitungszeit:** ~2-4 Minuten pro Minute Video
**Empfohlen für:** Schnellere Verarbeitung, wenn 4K nicht benötigt wird


## Parameter-Erklärungen

### Backend

- **`realesrgan`**: RealESRGAN-Engine, optimiert für natürliche Bilder/Fotos und Videos

### Scale Factor (nur RealESRGAN)

- **`2`**: 2x Upscaling (z.B. 720p → 1440p)
- **`4`**: 4x Upscaling (z.B. 720p → 2880p, typisch für DV → 4K)
- **`8`**: 8x Upscaling (experimentell, sehr langsam)

### Model (RealESRGAN)

- **`RealESRGAN_x4plus`**: Standard 4x Modell, beste Qualität für allgemeine Verwendung (empfohlen für Kassetten-Digitalisierung)
- **`RealESRGAN_x2plus`**: 2x Modell, schneller

### Face Enhance

- **`false`**: Keine Gesichtsverbesserung (Standard)
- **`true`**: Aktiviert GFPGAN für Gesichtsverbesserung (langsamer, aber bessere Gesichter)

### Encoder

- **`libx264rgb`**: RGB-Encoder, bessere Farbqualität, größere Dateien
- **`libx264`**: Standard H.264-Encoder, kompakter, schneller

### CRF (Constant Rate Factor)

- **`15-17`**: Sehr hohe Qualität, große Dateien
- **`18-20`**: Hohe Qualität, gute Balance (empfohlen)
- **`21-23`**: Standard-Qualität, kleinere Dateien
- **`24+`**: Niedrigere Qualität, sehr kleine Dateien

### Preset

- **`veryslow`**: Beste Kompression, langsamste Verarbeitung
- **`slow`**: Sehr gute Kompression, langsam
- **`medium`**: Standard, gute Balance
- **`fast`**: Schnellere Verarbeitung, größere Dateien
- **`veryfast`**: Sehr schnell, deutlich größere Dateien

### Tune

- **`film`**: Optimiert für Filmmaterial (empfohlen für DV)
- **`animation`**: Optimiert für Animationen
- **`grain`**: Erhält Filmkorn
- **`stillimage`**: Für Standbilder

---

## Empfehlungen nach Anwendungsfall

### Wichtige Familienaufnahmen / Archivmaterial
- **Profil:** RealESRGAN 4x HQ
- **Begründung:** Beste Qualität, Zeit spielt keine Rolle

### Standard-Digitalisierungen
- **Profil:** RealESRGAN 4x Standard
- **Begründung:** Gute Balance zwischen Qualität und Zeit

### Schnelle Durchsicht / Testläufe
- **Profil:** RealESRGAN 4x Fast
- **Begründung:** Schnell, akzeptable Qualität

### Batch-Processing (viele Kassetten)
- **Profil:** RealESRGAN 4x Fast oder RealESRGAN 2x
- **Begründung:** Zeitersparnis bei akzeptabler Qualität

---

## Performance-Hinweise

### GPU vs. CPU

- **GPU (CUDA/OpenCL):** Deutlich schneller (empfohlen)
- **CPU:** Langsamer, aber universell verfügbar

### Geschätzte Verarbeitungszeiten (pro Minute Video)

| Profil | GPU (RTX 3060) | GPU (RTX 4090) | CPU (i7-12700K) |
|--------|----------------|----------------|-----------------|
| RealESRGAN 4x HQ | ~15 Min | ~8 Min | ~60 Min |
| RealESRGAN 4x Balanced | ~8 Min | ~4 Min | ~30 Min |
| RealESRGAN 4x Fast | ~4 Min | ~2 Min | ~15 Min |
| RealESRGAN 2x | ~2 Min | ~1 Min | ~8 Min |

*Hinweis: Zeiten sind Schätzungen und können je nach Hardware und Videoinhalt variieren.*

---

## Dateigrößen (geschätzt)

### Pro Minute Video (nach Upscaling auf 4K)

| Profil | Dateigröße (ungefähr) |
|--------|----------------------|
| RealESRGAN 4x HQ (CRF 17) | ~500-800 MB |
| RealESRGAN 4x Balanced (CRF 18) | ~400-600 MB |
| RealESRGAN 4x Fast (CRF 20) | ~300-500 MB |
| RealESRGAN 2x (CRF 18) | ~200-400 MB |

*Hinweis: Dateigrößen hängen stark vom Videoinhalt ab (Bewegung, Details, etc.)*

---

## Konfiguration in settings.json

Beispiel für ein vollständiges Profil in der Konfigurationsdatei:

```json
{
  "upscaling": {
    "default_profile": "realesrgan_4x_hq",
    "profiles": {
      "realesrgan_4x_hq": {
        "backend": "realesrgan",
        "scale_factor": 4,
        "model": "RealESRGAN_x4plus",
        "face_enhance": false,
        "encoder": "libx264rgb",
        "encoder_options": {
          "crf": 17,
          "preset": "veryslow",
          "tune": "film"
        }
      }
    }
  }
}
```

---

## Troubleshooting

### "Model not found" Fehler
- Stelle sicher, dass das entsprechende Modell im Real-ESRGAN weights-Ordner vorhanden ist
- RealESRGAN-Modelle liegen in `dv2plex/bin/realesrgan/weights/`
- Lade fehlende Modelle von: https://github.com/xinntao/Real-ESRGAN/releases

### "GPU not available" Fehler
- Prüfe, ob PyTorch mit CUDA-Support installiert ist
- Real-ESRGAN nutzt PyTorch für GPU-Beschleunigung
- Fallback auf CPU ist möglich (aber sehr langsam)

### Sehr langsame Verarbeitung
- Prüfe GPU-Auslastung (Task Manager)
- Reduziere Preset (z.B. `veryslow` → `slow`)
- Erhöhe CRF leicht (z.B. `17` → `18`) für kleinere Dateien und schnellere Kompression

### Schlechte Qualität
- Reduziere CRF (z.B. `20` → `17`)
- Verwende `veryslow` Preset
- Stelle sicher, dass das richtige Modell verwendet wird (z.B. `RealESRGAN_x4plus`)

