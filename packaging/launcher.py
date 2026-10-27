"""Entry point of the packaged desktop app (PyInstaller)."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from dv2plex.cli import main

    sys.exit(main())
