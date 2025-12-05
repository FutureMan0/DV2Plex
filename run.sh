#!/bin/bash
# DV2Plex Start Script for Linux

# Activate virtual environment if present
if [ -d "venv" ]; then
    source venv/bin/activate
    python -m dv2plex.app
else
    # Fallback: Use system Python
    python3 -m dv2plex.app
fi
