#!/bin/bash
# DV2Plex Start-Skript für Linux

# Aktiviere Virtual Environment falls vorhanden
if [ -d "venv" ]; then
    source venv/bin/activate
    python -m dv2plex.app
else
    # Fallback: Verwende system Python
    python3 -m dv2plex.app
fi

