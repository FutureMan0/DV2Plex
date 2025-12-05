#!/bin/bash
# DV2Plex Start Script for Linux mit Dependenz-Check

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

ask_install() {
    local pkg="$1"
    local install_cmd=""

    if command -v apt-get &> /dev/null; then
        install_cmd="sudo apt-get install -y $pkg"
    elif command -v dnf &> /dev/null; then
        install_cmd="sudo dnf install -y $pkg"
    elif command -v yum &> /dev/null; then
        install_cmd="sudo yum install -y $pkg"
    elif command -v pacman &> /dev/null; then
        install_cmd="sudo pacman -S --noconfirm $pkg"
    else
        echo "⚠ Kein unterstützter Paketmanager gefunden. Bitte installiere $pkg manuell."
        return
    fi

    read -p "⚠ $pkg fehlt. Automatisch installieren? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "→ Installiere $pkg ..."
        eval "$install_cmd"
    else
        echo "✗ $pkg wurde nicht installiert. DV2Plex benötigt es ggf. für volle Funktionalität."
    fi
}

check_dep() {
    local cmd="$1"
    local pkg_name="$2"
    if command -v "$cmd" &> /dev/null; then
        echo "✓ $cmd vorhanden"
    else
        ask_install "$pkg_name"
    fi
}

echo "=== DV2Plex Start (mit Dependenz-Check) ==="

# Wichtige System-Dependencies prüfen (kann je nach Distribution anders heißen)
check_dep ffmpeg ffmpeg
check_dep dvgrab dvgrab

echo ""

# Virtuelle Umgebung nutzen, falls vorhanden
if [ -d "$SCRIPT_DIR/venv" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
    python "$SCRIPT_DIR/start.py"
else
    # Fallback: Verwende system Python
    python3 "$SCRIPT_DIR/start.py"
fi
