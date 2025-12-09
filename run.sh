#!/bin/bash
# DV2Plex Start Script for Linux with dependency check

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
        echo "⚠ No supported package manager found. Please install $pkg manually."
        return
    fi

    read -p "⚠ $pkg is missing. Install automatically? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "→ Installing $pkg ..."
        eval "$install_cmd"
    else
        echo "✗ $pkg was not installed. DV2Plex may need it for full functionality."
    fi
}

check_dep() {
    local cmd="$1"
    local pkg_name="$2"
    if command -v "$cmd" &> /dev/null; then
        echo "✓ $cmd available"
    else
        ask_install "$pkg_name"
    fi
}

echo "=== DV2Plex Start (with dependency check) ==="

# Check important system dependencies (may vary by distribution)
check_dep ffmpeg ffmpeg
check_dep dvgrab dvgrab

echo ""

# Prüfe, ob --no-gui übergeben wurde
USE_SUDO=false
for arg in "$@"; do
    if [ "$arg" = "--no-gui" ]; then
        USE_SUDO=true
        break
    fi
done

# Wenn --no-gui verwendet wird, starte mit sudo, damit sudo-Rechte nicht ablaufen
if [ "$USE_SUDO" = true ]; then
    # Prüfe, ob bereits als root ausgeführt
    if [ "$EUID" -eq 0 ]; then
        echo "ℹ Programm läuft bereits als root"
        USE_SUDO=false
    else
        echo "ℹ --no-gui Modus: Starte mit sudo, damit Kamera-Steuerung dauerhaft funktioniert"
        echo "   (sudo-Rechte laufen nicht ab, wenn das Programm als root gestartet wird)"
    fi
fi

# Use virtual environment if available
if [ -d "$SCRIPT_DIR/venv" ]; then
    if [ "$USE_SUDO" = true ]; then
        # Bei sudo: Verwende venv Python direkt mit vollständigem Pfad
        sudo -E "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/start.py" "$@"
    else
        source "$SCRIPT_DIR/venv/bin/activate"
        python "$SCRIPT_DIR/start.py" "$@"
    fi
else
    # Fallback: Use system Python
    if [ "$USE_SUDO" = true ]; then
        sudo -E python3 "$SCRIPT_DIR/start.py" "$@"
    else
        python3 "$SCRIPT_DIR/start.py" "$@"
    fi
fi
