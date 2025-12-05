# Upscaling Profile Reference

## Overview of Available Profiles

This table documents all available upscaling profiles with their parameters, use cases, and performance characteristics.

---

## RealESRGAN Profiles

### RealESRGAN 4x HQ (Highest Quality)

**Use Case:** Best quality for important recordings, time is not a factor

| Parameter | Value | Description |
|-----------|------|--------------|
| Backend | `realesrgan` | RealESRGAN engine |
| Scale Factor | `4` | 4x upscaling |
| Model | `RealESRGAN_x4plus` | RealESRGAN x4plus model (highest quality) |
| Encoder | `libx264rgb` | RGB encoder for better color quality |
| CRF | `17` | Very high quality (18-23 is standard) |
| Preset | `veryslow` | Slowest, but best compression |
| Tune | `film` | Optimized for film material |

**Estimated Processing Time:** ~10-20 minutes per minute of video (depending on GPU)
**Recommended for:** Important family recordings, archive material

---

### RealESRGAN 4x Standard

**Use Case:** Good balance between quality and speed

| Parameter | Value | Description |
|-----------|------|--------------|
| Backend | `realesrgan` | RealESRGAN engine |
| Scale Factor | `4` | 4x upscaling |
| Model | `RealESRGAN_x4plus` | RealESRGAN x4plus model |
| Face Enhance | `false` | No face enhancement |
| Encoder | `libx264` | Standard H.264 encoder |
| CRF | `18` | High quality |
| Preset | `slow` | Good balance |
| Tune | `film` | Optimized for film material |

**Estimated Processing Time:** ~5-10 minutes per minute of video
**Recommended for:** Standard digitizations

---

### RealESRGAN 4x Fast

**Use Case:** Fast processing, acceptable quality

| Parameter | Value | Description |
|-----------|------|--------------|
| Backend | `realesrgan` | RealESRGAN engine |
| Scale Factor | `4` | 4x upscaling |
| Model | `RealESRGAN_x4plus` | RealESRGAN x4plus model |
| Face Enhance | `false` | No face enhancement |
| Encoder | `libx264` | Standard H.264 encoder (faster) |
| CRF | `20` | Good quality |
| Preset | `medium` | Faster compression |
| Tune | `film` | Optimized for film material |

**Estimated Processing Time:** ~3-5 minutes per minute of video
**Recommended for:** Quick review, test runs

---

### RealESRGAN 2x

**Use Case:** 2x upscaling (faster than 4x)

| Parameter | Value | Description |
|-----------|------|--------------|
| Backend | `realesrgan` | RealESRGAN engine |
| Scale Factor | `2` | 2x upscaling |
| Model | `RealESRGAN_x2plus` | RealESRGAN x2plus model |
| Face Enhance | `false` | No face enhancement |
| Encoder | `libx264` | Standard H.264 encoder |
| CRF | `18` | High quality |
| Preset | `slow` | Good balance |
| Tune | `film` | Optimized for film material |

**Estimated Processing Time:** ~2-4 minutes per minute of video
**Recommended for:** Faster processing when 4K is not needed


## Parameter Explanations

### Backend

- **`realesrgan`**: RealESRGAN engine, optimized for natural images/photos and videos

### Scale Factor (RealESRGAN only)

- **`2`**: 2x upscaling (e.g., 720p → 1440p)
- **`4`**: 4x upscaling (e.g., 720p → 2880p, typical for DV → 4K)
- **`8`**: 8x upscaling (experimental, very slow)

### Model (RealESRGAN)

- **`RealESRGAN_x4plus`**: Standard 4x model, best quality for general use (recommended for tape digitization)
- **`RealESRGAN_x2plus`**: 2x model, faster

### Face Enhance

- **`false`**: No face enhancement (default)
- **`true`**: Enables GFPGAN for face enhancement (slower, but better faces)

### Encoder

- **`libx264rgb`**: RGB encoder, better color quality, larger files
- **`libx264`**: Standard H.264 encoder, more compact, faster

### CRF (Constant Rate Factor)

- **`15-17`**: Very high quality, large files
- **`18-20`**: High quality, good balance (recommended)
- **`21-23`**: Standard quality, smaller files
- **`24+`**: Lower quality, very small files

### Preset

- **`veryslow`**: Best compression, slowest processing
- **`slow`**: Very good compression, slow
- **`medium`**: Standard, good balance
- **`fast`**: Faster processing, larger files
- **`veryfast`**: Very fast, significantly larger files

### Tune

- **`film`**: Optimized for film material (recommended for DV)
- **`animation`**: Optimized for animations
- **`grain`**: Preserves film grain
- **`stillimage`**: For still images

---

## Recommendations by Use Case

### Important Family Recordings / Archive Material
- **Profile:** RealESRGAN 4x HQ
- **Reason:** Best quality, time is not a factor

### Standard Digitizations
- **Profile:** RealESRGAN 4x Standard
- **Reason:** Good balance between quality and time

### Quick Review / Test Runs
- **Profile:** RealESRGAN 4x Fast
- **Reason:** Fast, acceptable quality

### Batch Processing (many tapes)
- **Profile:** RealESRGAN 4x Fast or RealESRGAN 2x
- **Reason:** Time savings with acceptable quality

---

## Performance Notes

### GPU vs. CPU

- **GPU (CUDA/OpenCL):** Significantly faster (recommended)
- **CPU:** Slower, but universally available

### Estimated Processing Times (per minute of video)

| Profile | GPU (RTX 3060) | GPU (RTX 4090) | CPU (i7-12700K) |
|--------|----------------|----------------|-----------------|
| RealESRGAN 4x HQ | ~15 Min | ~8 Min | ~60 Min |
| RealESRGAN 4x Balanced | ~8 Min | ~4 Min | ~30 Min |
| RealESRGAN 4x Fast | ~4 Min | ~2 Min | ~15 Min |
| RealESRGAN 2x | ~2 Min | ~1 Min | ~8 Min |

*Note: Times are estimates and may vary depending on hardware and video content.*

---

## File Sizes (estimated)

### Per Minute of Video (after upscaling to 4K)

| Profile | File Size (approximately) |
|--------|----------------------|
| RealESRGAN 4x HQ (CRF 17) | ~500-800 MB |
| RealESRGAN 4x Balanced (CRF 18) | ~400-600 MB |
| RealESRGAN 4x Fast (CRF 20) | ~300-500 MB |
| RealESRGAN 2x (CRF 18) | ~200-400 MB |

*Note: File sizes depend heavily on video content (motion, details, etc.)*

---

## Configuration in settings.json

Example of a complete profile in the configuration file:

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

### "Model not found" Error
- Make sure the corresponding model is present in the Real-ESRGAN weights folder
- RealESRGAN models are located in `dv2plex/bin/realesrgan/weights/`
- Download missing models from: https://github.com/xinntao/Real-ESRGAN/releases

### "GPU not available" Error
- Check if PyTorch with CUDA support is installed
- Real-ESRGAN uses PyTorch for GPU acceleration
- Fallback to CPU is possible (but very slow)

### Very Slow Processing
- Check GPU usage (Task Manager)
- Reduce preset (e.g., `veryslow` → `slow`)
- Increase CRF slightly (e.g., `17` → `18`) for smaller files and faster compression

### Poor Quality
- Reduce CRF (e.g., `20` → `17`)
- Use `veryslow` preset
- Make sure the correct model is used (e.g., `RealESRGAN_x4plus`)
