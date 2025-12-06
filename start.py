"""
Direct entry point for DV2Plex
Can be executed directly: python start.py
"""

import sys
import argparse
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DV2Plex - MiniDV Digitalisierung")
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Startet Webserver statt GUI (für SSH-Zugriff)"
    )
    args = parser.parse_args()
    
    if args.no_gui:
        # Start webserver
        from dv2plex.web_app import main as web_main
        web_main()
    else:
        # Start GUI (default)
        from dv2plex.app import main
        main()

