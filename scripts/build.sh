#!/bin/bash
# Build script for DV2Plex with PyInstaller (Linux)
# Creates a complete, standalone Linux distribution

set -e  # Exit on errors

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Project root directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# PROJECT_ROOT is the parent directory (where requirements.txt is located)
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

# Parse command line arguments
AUTO_INSTALL=0
if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    echo "DV2Plex PyInstaller Build Script (Linux)"
    echo ""
    echo "Usage:"
    echo "  $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --auto-install, -y    Installs missing dependencies automatically"
    echo "  --help, -h            Shows this help"
    echo ""
    exit 0
fi

if [[ "$1" == "--auto-install" ]] || [[ "$1" == "-y" ]]; then
    AUTO_INSTALL=1
fi

echo "============================================================"
echo "DV2Plex PyInstaller Build Script"
echo "============================================================"
echo ""

# Functions
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

# Warning when running as sudo
if [ "$EUID" -eq 0 ]; then
    print_warning "Script is running as root!"
    print_info "It is recommended to run the script without sudo"
    print_info "to use the virtual environment correctly."
    echo ""
fi

# 0. Check and activate virtual environment
echo "0. Checking virtual environment..."
if [ -n "$VIRTUAL_ENV" ]; then
    print_success "Virtual environment active: $VIRTUAL_ENV"
    PYTHON_CMD="$VIRTUAL_ENV/bin/python"
elif [ -f "$PROJECT_ROOT/venv/bin/python" ]; then
    print_warning "Virtual environment found but not active. Activating..."
    source "$PROJECT_ROOT/venv/bin/activate"
    PYTHON_CMD="$PROJECT_ROOT/venv/bin/python"
    print_success "Virtual environment activated: $PROJECT_ROOT/venv"
elif [ -f "$PROJECT_ROOT/../venv/bin/python" ]; then
    print_warning "Virtual environment found in parent directory. Activating..."
    source "$PROJECT_ROOT/../venv/bin/activate"
    PYTHON_CMD="$PROJECT_ROOT/../venv/bin/python"
    print_success "Virtual environment activated: $PROJECT_ROOT/../venv"
else
    print_warning "No virtual environment found"
    print_info "Using system-wide Python (not recommended)"
    # Fallback to system-wide Python
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        print_error "Python not found!"
        exit 1
    fi
fi

# 1. Check Python
echo ""
echo "1. Checking Python installation..."
PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
if [ -n "$PYTHON_VERSION" ]; then
    print_success "Python found: $PYTHON_VERSION"
    print_info "Python path: $PYTHON_CMD"
else
    print_error "Python version could not be determined!"
    exit 1
fi

# 2. Check pip
echo ""
echo "2. Checking pip..."
if $PYTHON_CMD -m pip --version &> /dev/null; then
    print_success "pip available"
else
    print_error "pip not found!"
    exit 1
fi

# 3. Check if PyInstaller is installed
echo ""
echo "3. Checking PyInstaller..."
if $PYTHON_CMD -c "import PyInstaller" 2>/dev/null; then
    PYINSTALLER_VERSION=$($PYTHON_CMD -m PyInstaller --version 2>&1)
    print_success "PyInstaller found: $PYINSTALLER_VERSION"
else
    print_warning "PyInstaller not found. Installing..."
    $PYTHON_CMD -m pip install PyInstaller
    print_success "PyInstaller installed"
fi

# 4. Check Dependencies
echo ""
echo "4. Checking Python dependencies..."
MISSING_DEPS=()

check_dependency() {
    if $PYTHON_CMD -c "import $1" 2>/dev/null; then
        print_success "$1"
        return 0
    else
        print_warning "$1 missing"
        MISSING_DEPS+=("$1")
        return 0  # Always return 0 so set -e doesn't exit the script
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
    print_warning "Missing dependencies found!"
    echo ""
    
    if [ $AUTO_INSTALL -eq 1 ]; then
        echo "Installing dependencies automatically from requirements.txt..."
        $PYTHON_CMD -m pip install -r requirements.txt
        print_success "Dependencies installed"
    else
        read -p "Should I install the missing packages? (y/n) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Installing dependencies from requirements.txt..."
            $PYTHON_CMD -m pip install -r requirements.txt
            print_success "Dependencies installed"
        else
            print_error "Please install the missing dependencies manually:"
            echo "  pip install -r requirements.txt"
            echo ""
            echo "Or run the script with --auto-install:"
            echo "  ./build.sh --auto-install"
            exit 1
        fi
    fi
fi

# 5. Check ffmpeg (optional)
echo ""
echo "5. Checking ffmpeg..."
FFMPEG_FOUND=0

# Check local ffmpeg
if [ -f "$PROJECT_ROOT/dv2plex/bin/ffmpeg/bin/ffmpeg" ]; then
    print_success "ffmpeg found: $PROJECT_ROOT/dv2plex/bin/ffmpeg/bin/ffmpeg"
    FFMPEG_FOUND=1
fi

# Check system ffmpeg
if [ $FFMPEG_FOUND -eq 0 ] && command -v ffmpeg &> /dev/null; then
    FFMPEG_PATH=$(which ffmpeg)
    print_success "ffmpeg found in system PATH: $FFMPEG_PATH"
    FFMPEG_FOUND=1
fi

if [ $FFMPEG_FOUND -eq 0 ]; then
    print_warning "ffmpeg not found"
    print_info "ffmpeg is required when starting the application"
    print_info "Install ffmpeg system-wide or place it in:"
    print_info "  $PROJECT_ROOT/dv2plex/bin/ffmpeg/bin/ffmpeg"
fi

# 6. Clean old builds
echo ""
echo "6. Cleaning old builds..."
if [ -d "$PROJECT_ROOT/build" ]; then
    rm -rf "$PROJECT_ROOT/build"
    print_success "Build directory cleaned"
fi

if [ -d "$PROJECT_ROOT/dist" ]; then
    read -p "Delete old dist directory? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$PROJECT_ROOT/dist"
        print_success "dist directory cleaned"
    fi
fi

# 7. Run PyInstaller Build
echo ""
echo "7. Starting PyInstaller Build..."
echo "============================================================"

SPEC_FILE="$PROJECT_ROOT/scripts/dv2plex.spec"

if [ ! -f "$SPEC_FILE" ]; then
    print_error "Specification file not found: $SPEC_FILE"
    exit 1
fi

print_info "Using specification: $SPEC_FILE"
echo ""

$PYTHON_CMD -m PyInstaller \
    --clean \
    --noconfirm \
    "$SPEC_FILE"

if [ $? -eq 0 ]; then
    print_success "Build successful!"
else
    print_error "Build failed!"
    exit 1
fi

# 8. Copy additional files
echo ""
echo "8. Copying additional files..."

DIST_DIR="$PROJECT_ROOT/dist/DV2Plex"

if [ ! -d "$DIST_DIR" ]; then
    print_error "Dist directory not found: $DIST_DIR"
    exit 1
fi

# README
if [ -f "$PROJECT_ROOT/README.md" ]; then
    cp "$PROJECT_ROOT/README.md" "$DIST_DIR/"
    print_success "README.md copied"
fi

# Example configuration
if [ -f "$PROJECT_ROOT/Konfiguration_Beispiel.json" ]; then
    cp "$PROJECT_ROOT/Konfiguration_Beispiel.json" "$DIST_DIR/"
    print_success "Konfiguration_Beispiel.json copied"
fi

# Logo (if not already copied by PyInstaller)
if [ -f "$PROJECT_ROOT/dv2plex_logo.png" ]; then
    if [ ! -f "$DIST_DIR/dv2plex_logo.png" ]; then
        cp "$PROJECT_ROOT/dv2plex_logo.png" "$DIST_DIR/"
        print_success "Logo copied"
    else
        print_success "Logo already present"
    fi
fi

# Create directories
mkdir -p "$DIST_DIR/DV_Import"
mkdir -p "$DIST_DIR/logs"
print_success "Directories created"

# 9. Create startup script and .desktop file
echo ""
echo "9. Creating startup script..."

# Linux shell script
STARTUP_SH="$DIST_DIR/start.sh"
cat > "$STARTUP_SH" << 'EOF'
#!/bin/bash
# DV2Plex Startup Script

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Run the application
./DV2Plex "$@"
EOF
chmod +x "$STARTUP_SH"
print_success "start.sh created"

# Linux .desktop file (for desktop integration)
if [ -f "$DIST_DIR/dv2plex_logo.png" ]; then
    DESKTOP_FILE="$DIST_DIR/dv2plex.desktop"
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=DV2Plex
Comment=DV2Plex - Digital Video Processing Application
Exec=$DIST_DIR/start.sh
Icon=$DIST_DIR/dv2plex_logo.png
Terminal=false
Categories=AudioVideo;Video;
EOF
    chmod +x "$DESKTOP_FILE"
    print_success "dv2plex.desktop created"
fi

# 10. Summary
echo ""
echo "============================================================"
echo "Build completed!"
echo "============================================================"
echo ""
print_success "Distribution is located in: $DIST_DIR"
echo ""
echo "Notes:"
echo "  - ffmpeg must be installed separately (if not present)"
echo "  - Real-ESRGAN models will be automatically downloaded on first start"
echo "  - Start the application with:"
echo "    ./dist/DV2Plex/start.sh"
echo "    Or directly: ./dist/DV2Plex/DV2Plex"
echo ""

# Check file size
if [ -f "$DIST_DIR/DV2Plex" ]; then
    SIZE=$(du -sh "$DIST_DIR" | cut -f1)
    print_info "Total distribution size: $SIZE"
fi

echo ""
print_success "Done!"
