"""
Logging to the console and to a rotating file (logging.log_directory, dv2plex.log).

The file keeps what the Logs tab shows only while the app runs, for bug reports.
The API token is masked in every line.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Any, Optional

from .access import RedactTokenFilter

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


def setup_logging(config: Any = None, level: Optional[str] = None) -> Optional[Path]:
    """Configures the root logger once. Returns the log file, or None if it cannot be written."""
    global _configured
    root = logging.getLogger()
    level_name = (level or (config.get("logging.level", "INFO") if config else "INFO") or "INFO").upper()
    root.setLevel(getattr(logging, level_name, logging.INFO))
    if _configured:
        return None
    _configured = True

    redact = RedactTokenFilter()
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(FORMAT))
    console.addFilter(redact)
    root.addHandler(console)

    log_file = None
    if config is not None:
        try:
            directory = Path(config.get_log_directory())
            directory.mkdir(parents=True, exist_ok=True)
            log_file = directory / "dv2plex.log"
            backups = max(1, int(config.get("logging.max_log_files", 10) or 10))
            handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=backups, encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter(FORMAT))
            handler.addFilter(redact)
            root.addHandler(handler)
        except (OSError, ValueError) as e:
            logging.getLogger(__name__).warning("Cannot write the log file (%s); logging to the console only.", e)
            log_file = None
    for noisy in ("multipart", "PIL", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_file
