"""
Test setup.

- service.py imports poster_generation (cv2, scikit-learn, rembg) and cover_generation
  (Pillow, torch, diffusers) at module level. The tests need neither, so both are stubbed.
- Config, and web_app on import, write settings files; they go to a temporary folder
  instead of dv2plex/config/.
"""

import atexit
import shutil
import sys
import tempfile
import types
from pathlib import Path

for _module_name, _class_name in (
    ("dv2plex.poster_generation", "PosterGenerationEngine"),
    ("dv2plex.cover_generation", "CoverGenerationEngine"),
):
    if _module_name not in sys.modules:
        _stub = types.ModuleType(_module_name)
        setattr(_stub, _class_name, type(_class_name, (), {}))
        sys.modules[_module_name] = _stub

import dv2plex.config as _config  # noqa: E402

_TEST_CONFIG_DIR = Path(tempfile.mkdtemp(prefix="dv2plex-test-config-"))
atexit.register(shutil.rmtree, _TEST_CONFIG_DIR, True)
_config.CONFIG_DIR = _TEST_CONFIG_DIR
