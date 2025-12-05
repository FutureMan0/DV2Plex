#!/bin/bash
# Helper script to find FireWire devices

echo "Searching for FireWire devices..."
echo ""

if command -v dvgrab &> /dev/null; then
    dvgrab --list
else
    echo "dvgrab not found."
    echo "Please install dvgrab:"
    echo "  Debian/Ubuntu: sudo apt install dvgrab"
    echo "  Fedora: sudo dnf install dvgrab"
    echo "  Arch: sudo pacman -S dvgrab"
    echo ""
    echo "Or run ./setup.sh for automatic installation."
fi

echo ""
echo "Look for the device path (e.g., /dev/raw1394)"
echo "and optionally enter it in the configuration."
echo "Automatic detection usually works without configuration."
