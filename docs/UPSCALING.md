# Upscaling profiles

A profile says how a merged tape becomes an HD or 4K film. The defaults are in
[`dv2plex/config.py`](../dv2plex/config.py); you can change them or add your own under
`upscaling.profiles` in `settings.local.json`. `upscaling.default_profile` is the one used
when none is chosen (and by the automatic chain after a capture).

## The defaults

| Profile | Backend | Scale | Model | Tile | CRF | Preset | Tune |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| `realesrgan_4x_hq` | realesrgan | 4× | RealESRGAN_x4plus | 400 | 17 | veryfast | film |
| `realesrgan_4x_balanced` | realesrgan | 4× | RealESRGAN_x4plus | 400 | 18 | veryfast | film |
| `realesrgan_4x_fast` | realesrgan | 4× | RealESRGAN_x4plus | 400 | 20 | veryfast | film |
| `realesrgan_2x` (default) | realesrgan | 2× | RealESRGAN_x4plus | 400 | 18 | slow | film |
| `ffmpeg_hd` | ffmpeg | 2× | — | — | 18 | veryfast | film |
| `ffmpeg_fast` | ffmpeg | 4× | — | — | 20 | veryfast | film |

All of them deinterlace DV first (`"deinterlace": true`).

## What happens

**realesrgan:** the Real-ESRGAN video script (PyTorch, `dv2plex/bin/realesrgan/`) upscales the
deinterlaced frames to twice their size. For a 2× profile that is the film, encoded with the
profile's CRF and preset. For a 4× profile, ffmpeg scales that result on to 4K with Lanczos,
using the profile's encoder settings.

**ffmpeg:** deinterlace, then Lanczos scaling; no AI. Works on any computer and is fast, but
does not add detail. It is the only backend in the desktop app.

**Size and aspect.** The output has square pixels and keeps the tape's shape:

| Tape | 2× (`realesrgan_2x`) | 2× (`ffmpeg_hd`) | 4× |
| :-- | :-- | :-- | :-- |
| PAL 4:3 (720 × 576) | 1440 × 1152, shown as 4:3 | 1440 × 1080 | 2880 × 2160 |
| PAL 16:9 | 1440 × 1152, shown as 16:9 | 1920 × 1080 | 3840 × 2160 |
| NTSC 4:3 (720 × 480) | 1440 × 960, shown as 4:3 | 1440 × 1080 | 2880 × 2160 |

`realesrgan_2x` keeps Real-ESRGAN's pixels and marks their aspect in the H.264 stream, so
players show it with the right shape.

Every film is H.264 with 4:2:0 colour (plays on TVs, browsers and every Plex client) and AAC
audio, with its index at the start of the file.

## Options of a profile

| Key | Meaning |
| :-- | :-- |
| `backend` | `realesrgan` or `ffmpeg` |
| `scale_factor` | `2` fits into 1920 × 1080 (ffmpeg) or doubles the size (Real-ESRGAN); `4` fits into 3840 × 2160; any other number multiplies the display size |
| `model` | Real-ESRGAN model: `RealESRGAN_x4plus` (photos and video), `realesr-general-x4v3`, `RealESRGAN_x2plus`, … The weights download on first use |
| `tile_size`, `tile_pad` | Real-ESRGAN works in tiles; a smaller `tile_size` (e.g. 200) needs less GPU memory |
| `face_enhance` | GFPGAN for faces (needs `gfpgan`); off by default |
| `deinterlace` | `true` (default) deinterlaces DV (bottom field first) with bwdif; `false` keeps the fields |
| `encoder` | ffmpeg video encoder, normally `libx264` |
| `encoder_options` | `crf` (lower is better and larger, 17–20 is near transparent), `preset` (slower compresses better), and any other encoder option such as `tune` |

## Hardware

Real-ESRGAN uses an NVIDIA GPU (CUDA) when there is one, Apple's GPU (MPS) on a Mac, and the
CPU otherwise. On the CPU it takes about a minute per frame of DV, which is days per tape;
use `ffmpeg_hd` or `ffmpeg_fast` there. Measured on an Apple M-series Mac: 3 PAL frames to
1440 × 1152 took 174 s on the CPU and 9 s on MPS.

## Troubleshooting

- **"Real-ESRGAN needs PyTorch …":** install the upscaling packages, `pip install -r requirements.txt`.
- **Out of GPU memory:** a profile with `"tile_size": 200`.
- **Combing on moving edges:** the profile has `"deinterlace": false`, or the source is not DV-sized.
- **Very slow:** no GPU was found; check `torch.cuda.is_available()`, or use an ffmpeg profile.
