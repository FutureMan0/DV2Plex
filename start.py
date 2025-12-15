"""
Direct entry point for DV2Plex
Can be executed directly: python start.py
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    from dv2plex.cli import main

    main()

