#!/bin/bash
# Build-Skript für DV2Plex mit PyInstaller
# Erstellt eine vollständige, eigenständige Distribution

set -e  # Beende bei Fehlern

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Projekt-Root-Verzeichnis
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR"
cd "$PROJECT_ROOT"

echo "============================================================"
echo "DV2Plex PyInstaller Build-Skript"
echo "============================================================"
echo ""

# Funktionen
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "  $1"
}

# 1. Prüfe Python
echo "1. Prüfe Python-Installation..."
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    print_success "Python gefunden: $PYTHON_VERSION"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
    PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')
    print_success "Python gefunden: $PYTHON_VERSION"
else
    print_error "Python nicht gefunden!"
    exit 1
fi

# 2. Prüfe pip
echo ""
echo "2. Prüfe pip..."
if $PYTHON_CMD -m pip --version &> /dev/null; then
    print_success "pip verfügbar"
else
    print_error "pip nicht gefunden!"
    exit 1
fi

# 3. Prüfe ob PyInstaller installiert ist
echo ""
echo "3. Prüfe PyInstaller..."
if $PYTHON_CMD -c "import PyInstaller" 2>/dev/null; then
    PYINSTALLER_VERSION=$($PYTHON_CMD -m PyInstaller --version 2>&1)
    print_success "PyInstaller gefunden: $PYINSTALLER_VERSION"
else
    print_warning "PyInstaller nicht gefunden. Installiere..."
    $PYTHON_CMD -m pip install PyInstaller
    print_success "PyInstaller installiert"
fi

# 4. Prüfe Dependencies
echo ""
echo "4. Prüfe Python-Dependencies..."
MISSING_DEPS=()

check_dependency() {
    if $PYTHON_CMD -c "import $1" 2>/dev/null; then
        print_success "$1"
        return 0
    else
        print_warning "$1 fehlt"
        MISSING_DEPS+=("$1")
        return 1
    fi
}

check_dependency "PySide6"
check_dependency "torch"
check_dependency "torchvision"
check_dependency "basicsr"
check_dependency "cv2"
check_dependency "numpy"
check_dependency "PIL"

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo ""
    print_warning "Fehlende Dependencies gefunden!"
    echo ""
    read -p "Soll ich die fehlenden Packages installieren? (j/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[JjYy]$ ]]; then
        echo "Installiere Dependencies aus requirements.txt..."
        $PYTHON_CMD -m pip install -r requirements.txt
        print_success "Dependencies installiert"
    else
        print_error "Bitte installiere die fehlenden Dependencies manuell:"
        echo "  pip install -r requirements.txt"
        exit 1
    fi
fi

# 5. Prüfe ffmpeg (optional)
echo ""
echo "5. Prüfe ffmpeg..."
FFMPEG_FOUND=0

# Prüfe lokales ffmpeg
if [ -f "$PROJECT_ROOT/dv2plex/bin/ffmpeg/bin/ffmpeg" ]; then
    print_success "ffmpeg gefunden: $PROJECT_ROOT/dv2plex/bin/ffmpeg/bin/ffmpeg"
    FFMPEG_FOUND=1
elif [ -f "$PROJECT_ROOT/dv2plex/bin/ffmpeg/bin/ffmpeg.exe" ]; then
    print_success "ffmpeg gefunden: $PROJECT_ROOT/dv2plex/bin/ffmpeg/bin/ffmpeg.exe"
    FFMPEG_FOUND=1
fi

# Prüfe System-ffmpeg
if [ $FFMPEG_FOUND -eq 0 ] && command -v ffmpeg &> /dev/null; then
    FFMPEG_PATH=$(which ffmpeg)
    print_success "ffmpeg im System-PATH gefunden: $FFMPEG_PATH"
    FFMPEG_FOUND=1
fi

if [ $FFMPEG_FOUND -eq 0 ]; then
    print_warning "ffmpeg nicht gefunden"
    print_info "ffmpeg wird beim Start der Anwendung benötigt"
    print_info "Installiere ffmpeg systemweit oder platziere es in:"
    print_info "  $PROJECT_ROOT/dv2plex/bin/ffmpeg/bin/ffmpeg"
fi

# 6. Bereinige alte Builds
echo ""
echo "6. Bereinige alte Builds..."
if [ -d "$PROJECT_ROOT/build" ]; then
    rm -rf "$PROJECT_ROOT/build"
    print_success "Build-Verzeichnis bereinigt"
fi

if [ -d "$PROJECT_ROOT/dist" ]; then
    read -p "Altes dist-Verzeichnis löschen? (j/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[JjYy]$ ]]; then
        rm -rf "$PROJECT_ROOT/dist"
        print_success "dist-Verzeichnis bereinigt"
    fi
fi

# 7. Führe PyInstaller Build aus
echo ""
echo "7. Starte PyInstaller Build..."
echo "============================================================"

SPEC_FILE="$PROJECT_ROOT/scripts/dv2plex.spec"

if [ ! -f "$SPEC_FILE" ]; then
    print_error "Spezifikationsdatei nicht gefunden: $SPEC_FILE"
    exit 1
fi

print_info "Verwende Spezifikation: $SPEC_FILE"
echo ""

$PYTHON_CMD -m PyInstaller \
    --clean \
    --noconfirm \
    "$SPEC_FILE"

if [ $? -eq 0 ]; then
    print_success "Build erfolgreich!"
else
    print_error "Build fehlgeschlagen!"
    exit 1
fi

# 8. Kopiere zusätzliche Dateien
echo ""
echo "8. Kopiere zusätzliche Dateien..."

DIST_DIR="$PROJECT_ROOT/dist/DV2Plex"

if [ ! -d "$DIST_DIR" ]; then
    print_error "Dist-Verzeichnis nicht gefunden: $DIST_DIR"
    exit 1
fi

# README
if [ -f "$PROJECT_ROOT/README.md" ]; then
    cp "$PROJECT_ROOT/README.md" "$DIST_DIR/"
    print_success "README.md kopiert"
fi

# Beispiel-Konfiguration
if [ -f "$PROJECT_ROOT/Konfiguration_Beispiel.json" ]; then
    cp "$PROJECT_ROOT/Konfiguration_Beispiel.json" "$DIST_DIR/"
    print_success "Konfiguration_Beispiel.json kopiert"
fi

# Erstelle Verzeichnisse
mkdir -p "$DIST_DIR/DV_Import"
mkdir -p "$DIST_DIR/logs"
print_success "Verzeichnisse erstellt"

# 9. Erstelle Startup-Skripte
echo ""
echo "9. Erstelle Startup-Skripte..."

# Linux/Mac Shell-Skript
STARTUP_SH="$DIST_DIR/start.sh"
cat > "$STARTUP_SH" << 'EOF'
#!/bin/bash
# DV2Plex Startup-Skript

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Führe die Anwendung aus
./DV2Plex "$@"
EOF
chmod +x "$STARTUP_SH"
print_success "start.sh erstellt"

# Windows Batch-Datei
STARTUP_BAT="$DIST_DIR/start.bat"
cat > "$STARTUP_BAT" << 'EOF'
@echo off
REM DV2Plex Startup-Skript

cd /d "%~dp0"
DV2Plex.exe %*
EOF
print_success "start.bat erstellt"

# 10. Zusammenfassung
echo ""
echo "============================================================"
echo "Build abgeschlossen!"
echo "============================================================"
echo ""
print_success "Distribution befindet sich in: $DIST_DIR"
echo ""
echo "Hinweise:"
echo "  - ffmpeg muss separat installiert werden (falls nicht vorhanden)"
echo "  - Real-ESRGAN Modelle werden beim ersten Start automatisch heruntergeladen"
echo "  - Starte die Anwendung mit:"
echo "    Linux/Mac:   ./dist/DV2Plex/start.sh"
echo "    Windows:     dist\\DV2Plex\\start.bat"
echo "    Oder direkt: ./dist/DV2Plex/DV2Plex"
echo ""

# Prüfe Dateigröße
if [ -f "$DIST_DIR/DV2Plex" ] || [ -f "$DIST_DIR/DV2Plex.exe" ]; then
    if [ -f "$DIST_DIR/DV2Plex" ]; then
        EXE_FILE="$DIST_DIR/DV2Plex"
    else
        EXE_FILE="$DIST_DIR/DV2Plex.exe"
    fi
    
    SIZE=$(du -sh "$DIST_DIR" | cut -f1)
    print_info "Gesamtgröße der Distribution: $SIZE"
fi

echo ""
print_success "Fertig!"
