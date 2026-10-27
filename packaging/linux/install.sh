#!/bin/sh
# Installs DV2Plex for the current user: ~/.local/opt/dv2plex and a menu entry.
# Uninstall: rm -rf ~/.local/opt/dv2plex ~/.local/share/applications/dv2plex.desktop
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="${XDG_DATA_HOME:-$HOME/.local/share}/../opt/dv2plex"
TARGET="$(mkdir -p "$TARGET" && cd "$TARGET" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

rm -rf "$TARGET/DV2Plex"
cp -R "$HERE/DV2Plex" "$TARGET/"
cp "$HERE/dv2plex.png" "$HERE/LICENSE" "$HERE/THIRD_PARTY_NOTICES.md" "$TARGET/"
mkdir -p "$APPS"
sed "s#@INSTALL_DIR@#$TARGET#g" "$HERE/dv2plex.desktop" > "$APPS/dv2plex.desktop"
chmod +x "$TARGET/DV2Plex/DV2Plex"

echo "DV2Plex is installed in $TARGET and in your application menu."
echo "For capture you also need dvgrab (sudo apt install dvgrab) and a FireWire port."
echo "Without WebKitGTK (sudo apt install gir1.2-webkit2-4.1) DV2Plex opens in your browser."
