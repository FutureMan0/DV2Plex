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

# Use virtual environment if available
if [ -d "$SCRIPT_DIR/venv" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
    python "$SCRIPT_DIR/start.py"
else
    # Fallback: Use system Python
    python3 "$SCRIPT_DIR/start.py"
fi
