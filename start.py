"""
Direkter Startpunkt für DV2Plex
Kann direkt ausgeführt werden: python start.py
"""

import sys
from pathlib import Path

# Füge Projekt-Root zum Python-Pfad hinzu
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Importiere und starte die Anwendung
from dv2plex.app import main

if __name__ == "__main__":
    main()

