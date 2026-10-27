# Third-party notices

DV2Plex itself is under the [MIT License](LICENSE). It contains, bundles or uses the
following work of others. Licences of the packages inside a desktop build are also listed
in `THIRD_PARTY_LICENSES.txt` next to the program, generated during the build.

## Contained in this repository

### Real-ESRGAN (modified)

`dv2plex/bin/realesrgan/` — Copyright (c) 2021, Xintao Wang.
BSD 3-Clause License, full text in [dv2plex/bin/realesrgan/LICENSE](dv2plex/bin/realesrgan/LICENSE).
Source: <https://github.com/xinntao/Real-ESRGAN>

DV2Plex changed `inference_realesrgan_video.py` (runs with current torchvision, without CUDA,
on Apple GPUs; half precision only on CUDA; AAC audio; deinterlacing, CRF and preset options)
and added `realesrgan/version.py`. The changes are marked with "DV2Plex" in the code and are
under the same BSD 3-Clause License.

## Bundled in the desktop app

| Component | Licence | Source |
| :-- | :-- | :-- |
| Python | PSF License 2.0 | <https://www.python.org/> |
| FastAPI | MIT | <https://github.com/fastapi/fastapi> |
| Starlette | BSD 3-Clause | <https://github.com/encode/starlette> |
| Pydantic, pydantic-core | MIT | <https://github.com/pydantic/pydantic> |
| Uvicorn | BSD 3-Clause | <https://github.com/encode/uvicorn> |
| websockets | BSD 3-Clause | <https://github.com/python-websockets/websockets> |
| h11, anyio | MIT | <https://github.com/python-hyper/h11>, <https://github.com/agronholm/anyio> |
| pywebview | BSD 3-Clause | <https://github.com/r0x0r/pywebview> |
| pythonnet (Windows) | MIT | <https://github.com/pythonnet/pythonnet> |
| PyObjC (macOS) | MIT | <https://github.com/ronaldoussoren/pyobjc> |
| PyGObject (Linux) | LGPL 2.1 or later | <https://gitlab.gnome.org/GNOME/pygobject> |
| Pillow | MIT-CMU (HPND) | <https://github.com/python-pillow/Pillow> |
| PyInstaller bootloader | GPL 2.0 with an exception that allows bundling any program | <https://github.com/pyinstaller/pyinstaller> |

### FFmpeg

The desktop app contains an FFmpeg build with libx264, which makes that build GPL version 3
(libx264 is GPL 2.0 or later). It is a separate program that DV2Plex runs; its licence text
and the address it was downloaded from are in `dv2plex/bin/ffmpeg/` inside the package. The
source code of FFmpeg is at <https://ffmpeg.org/download.html>, that of the builds at:

- Windows: <https://www.gyan.dev/ffmpeg/builds/> (or <https://github.com/BtbN/FFmpeg-Builds>)
- macOS: <https://ffmpeg.martin-riedl.de/>
- Linux: <https://johnvansickle.com/ffmpeg/>

FFmpeg is a trademark of Fabrice Bellard, originator of the FFmpeg project.

## Used when installed (not part of this repository or the desktop app)

| Component | Licence | Used for |
| :-- | :-- | :-- |
| [dvgrab](https://github.com/ddennedy/dvgrab) | GPL 2.0 | capture over FireWire (separate program) |
| [libraw1394](https://ieee1394.docs.kernel.org/), libavc1394 | LGPL 2.1 | FireWire access for dvgrab |
| [FFmpeg](https://ffmpeg.org/) from your system | LGPL 2.1 or GPL, depending on the build | everything after the capture |
| [PyTorch](https://pytorch.org/), torchvision | BSD 3-Clause | Real-ESRGAN |
| [BasicSR](https://github.com/XPixelGroup/BasicSR) | Apache 2.0 | Real-ESRGAN |
| [facexlib](https://github.com/xinntao/facexlib) | MIT | Real-ESRGAN face option |
| [GFPGAN](https://github.com/TencentARC/GFPGAN) | Apache 2.0 (some parts other licences, see its repository) | Real-ESRGAN face option |
| [OpenCV](https://opencv.org/) (opencv-python) | Apache 2.0 | Real-ESRGAN, full poster |
| [NumPy](https://numpy.org/) | BSD 3-Clause | Real-ESRGAN, full poster |
| [ffmpeg-python](https://github.com/kkroening/ffmpeg-python) | Apache 2.0 | Real-ESRGAN |
| [Diffusers](https://github.com/huggingface/diffusers), [Transformers](https://github.com/huggingface/transformers), [Accelerate](https://github.com/huggingface/accelerate), [safetensors](https://github.com/huggingface/safetensors) | Apache 2.0 | Stable Diffusion covers |
| [rembg](https://github.com/danielgatis/rembg) | MIT | full poster (cut-out) |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | MIT | full poster (cut-out) |
| [Playwright](https://github.com/microsoft/playwright-python) and Chromium | Apache 2.0; Chromium: BSD 3-Clause and others | full poster rendering |

## Models downloaded on first use

| Model | Licence | Notes |
| :-- | :-- | :-- |
| RealESRGAN_x4plus and the other Real-ESRGAN weights | BSD 3-Clause | from the Real-ESRGAN releases on GitHub |
| GFPGAN v1.3 (face option only) | see the GFPGAN repository | |
| [Stable Diffusion v1.5](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5) | CreativeML Open RAIL-M | Its use restrictions apply to the covers you make with it |
| U²-Net (via rembg) | Apache 2.0 | full poster cut-out |

## Fonts and icons

The interface uses the fonts installed on the system (IBM Plex Sans and Mono if present) and
loads none from the internet. Its icons and the app icon were drawn for DV2Plex and are under
the MIT License.
