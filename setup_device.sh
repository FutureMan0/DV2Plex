#!/bin/bash
# Hilfsskript zum Finden von FireWire-Geräten

echo "Suche nach FireWire-Geräten..."
echo ""

if command -v dvgrab &> /dev/null; then
    dvgrab --list
else
    echo "dvgrab nicht gefunden."
    echo "Bitte installieren Sie dvgrab:"
    echo "  Debian/Ubuntu: sudo apt install dvgrab"
    echo "  Fedora: sudo dnf install dvgrab"
    echo "  Arch: sudo pacman -S dvgrab"
    echo ""
    echo "Oder führen Sie ./setup.sh aus für automatische Installation."
fi

echo ""
echo "Suchen Sie nach dem Gerätepfad (z.B. /dev/raw1394)"
echo "und tragen Sie diesen optional in die Konfiguration ein."
echo "Die automatische Erkennung funktioniert normalerweise ohne Konfiguration."

