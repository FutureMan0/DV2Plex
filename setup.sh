#!/bin/bash
# Automatic Setup Script for DV2Plex (Linux)

set -e

echo "=========================================="
echo "DV2Plex - Automatic Setup (Linux)"
echo "=========================================="
echo ""

# Check if we are root (for package installation)
NEED_SUDO=false

# Function to check commands
check_command() {
    if command -v "$1" &> /dev/null; then
        echo "✓ $1 found"
        return 0
    else
        echo "✗ $1 not found"
        return 1
    fi
}

# Function to install packages
install_package() {
    if [ -f /etc/debian_version ]; then
        # Debian/Ubuntu
        echo "Installing $1 with apt..."
        sudo apt-get update
        sudo apt-get install -y "$1"
    elif [ -f /etc/redhat-release ]; then
        # RedHat/CentOS/Fedora
        echo "Installing $1 with yum/dnf..."
        if command -v dnf &> /dev/null; then
            sudo dnf install -y "$1"
        else
            sudo yum install -y "$1"
        fi
    elif [ -f /etc/arch-release ]; then
        # Arch Linux
        echo "Installing $1 with pacman..."
        sudo pacman -S --noconfirm "$1"
    else
        echo "Unknown distribution. Please install $1 manually."
        return 1
    fi
}

# 1. Check Python
echo "1. Checking Python..."
if ! check_command python3; then
    echo "Python 3 not found. Installing..."
    install_package python3
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
echo "Python Version: $PYTHON_VERSION"

# Check Python 3.10+
if python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "✓ Python 3.10+ found"
else
    echo "✗ Python 3.10+ required. Please update Python."
    exit 1
fi

# 2. Check pip
echo ""
echo "2. Checking pip..."
if ! check_command pip3; then
    echo "pip3 not found. Installing..."
    install_package python3-pip
fi

# 3. Check dvgrab
echo ""
echo "3. Checking dvgrab..."
if ! check_command dvgrab; then
    echo "dvgrab not found. Installing..."
    if [ -f /etc/debian_version ]; then
        install_package dvgrab
    elif [ -f /etc/redhat-release ]; then
        if command -v dnf &> /dev/null; then
            sudo dnf install -y dvgrab
        else
            echo "dvgrab may not be in the standard repositories."
            echo "Please install dvgrab manually."
        fi
    elif [ -f /etc/arch-release ]; then
        install_package dvgrab
    else
        echo "Please install dvgrab manually for your distribution."
    fi
fi

# 4. Check ffmpeg
echo ""
echo "4. Checking ffmpeg..."
if ! check_command ffmpeg; then
    echo "ffmpeg not found. Installing..."
    if [ -f /etc/debian_version ]; then
        install_package ffmpeg
    elif [ -f /etc/redhat-release ]; then
        if command -v dnf &> /dev/null; then
            sudo dnf install -y ffmpeg
        else
            sudo yum install -y ffmpeg
        fi
    elif [ -f /etc/arch-release ]; then
        install_package ffmpeg
    else
        echo "Please install ffmpeg manually for your distribution."
    fi
fi

# 5. Check FireWire drivers
echo ""
echo "5. Checking FireWire drivers..."
if [ -f /etc/debian_version ]; then
    if ! dpkg -l | grep -q libraw1394; then
        echo "FireWire drivers not found. Installing..."
        install_package libraw1394-dev
        install_package libavc1394-dev
    else
        echo "✓ FireWire drivers found"
    fi
elif [ -f /etc/redhat-release ]; then
    if ! rpm -qa | grep -q libraw1394; then
        echo "FireWire drivers not found. Installing..."
        if command -v dnf &> /dev/null; then
            sudo dnf install -y libraw1394-devel libavc1394-devel
        else
            sudo yum install -y libraw1394-devel libavc1394-devel
        fi
    else
        echo "✓ FireWire drivers found"
    fi
elif [ -f /etc/arch-release ]; then
    if ! pacman -Q libraw1394 &> /dev/null; then
        echo "FireWire drivers not found. Installing..."
        install_package libraw1394
        install_package libavc1394
    else
        echo "✓ FireWire drivers found"
    fi
else
    echo "Please install libraw1394 and libavc1394 manually."
fi

# 6. Install Python Dependencies
echo ""
echo "6. Installing Python dependencies..."

# Check if python3-venv is installed
if ! python3 -m venv --help &> /dev/null; then
    echo "python3-venv not found. Installing..."
    if [ -f /etc/debian_version ]; then
        install_package python3-venv
    elif [ -f /etc/redhat-release ]; then
        if command -v dnf &> /dev/null; then
            sudo dnf install -y python3-virtualenv
        else
            sudo yum install -y python3-virtualenv
        fi
    elif [ -f /etc/arch-release ]; then
        install_package python-virtualenv
    else
        echo "⚠ Please install python3-venv manually"
    fi
fi

# Create virtual environment if not present
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    if python3 -m venv venv; then
        echo "✓ Virtual environment created"
    else
        echo "✗ Error creating virtual environment"
        echo "Trying installation with --user flag..."
        pip3 install -r requirements.txt --user --break-system-packages || {
            echo "✗ Installation failed. Please install manually:"
            echo "  sudo apt install python3-venv"
            echo "  python3 -m venv venv"
            echo "  source venv/bin/activate"
            echo "  pip install -r requirements.txt"
        }
        exit 0  # Continue with setup even if venv fails
    fi
fi

# Activate venv and install dependencies (if venv exists)
if [ -d "venv" ] && [ -f "venv/bin/activate" ]; then
    echo "Activating virtual environment and installing dependencies..."
    
    # Activate venv
    source venv/bin/activate
    
    # Verify venv is activated
    if [ -z "$VIRTUAL_ENV" ]; then
        echo "⚠ Venv activation failed, using venv Python directly..."
        VENV_PYTHON="$(pwd)/venv/bin/python"
        VENV_PIP="$(pwd)/venv/bin/pip"
    else
        echo "✓ Virtual environment activated: $VIRTUAL_ENV"
        VENV_PYTHON="python"
        VENV_PIP="pip"
    fi
    
    # Upgrade pip
    echo "Upgrading pip..."
    "$VENV_PIP" install --upgrade pip
    
    # Install dependencies
    echo "Installing Python dependencies..."
    "$VENV_PIP" install -r requirements.txt
    
    # Verify installation
    if [ $? -eq 0 ]; then
        echo "✓ Python dependencies installed successfully"
    else
        echo "✗ Installation failed"
        exit 1
    fi
    
    # Deactivate venv (only if it was activated via source)
    if [ -n "$VIRTUAL_ENV" ]; then
        deactivate
    fi
else
    echo "⚠ Virtual environment could not be created"
    echo "Trying installation with --user flag..."
    pip3 install -r requirements.txt --user --break-system-packages || {
        echo "✗ Installation failed. Please install manually:"
        echo "  sudo apt install python3-venv"
        echo "  python3 -m venv venv"
        echo "  source venv/bin/activate"
        echo "  pip install -r requirements.txt"
    }
fi

# 7. Create necessary directories
echo ""
echo "7. Creating directories..."
mkdir -p dv2plex/DV_Import
mkdir -p dv2plex/logs
mkdir -p dv2plex/config
mkdir -p dv2plex/PlexMovies

# 8. Configure FireWire permissions
echo ""
echo "8. Configuring FireWire permissions..."
if [ -e /dev/raw1394 ]; then
    # Check if user is already in video group
    if groups | grep -q video; then
        echo "✓ User is already in video group"
    else
        echo "Adding user to video group..."
        sudo usermod -a -G video "$USER"
        echo "⚠ Please log out and log back in for the group change to take effect."
    fi
    
    # Set permissions (if needed)
    if [ -w /dev/raw1394 ]; then
        echo "✓ Permissions for /dev/raw1394 are correct"
    else
        echo "⚠ /dev/raw1394 is not writable. You may need to log out and back in."
    fi
else
    echo "⚠ /dev/raw1394 not found. Please connect a FireWire device."
fi

# 9. Test FireWire connection
echo ""
echo "9. Testing FireWire connection..."
if command -v dvgrab &> /dev/null; then
    if dvgrab --list 2>&1 | grep -q "Device"; then
        echo "✓ FireWire device detected:"
        dvgrab --list
    else
        echo "⚠ No FireWire device found. Please connect a camera."
    fi
else
    echo "⚠ dvgrab not available, cannot test FireWire connection."
fi

# 10. Create default configuration if not present
echo ""
echo "10. Creating default configuration..."
if [ ! -f dv2plex/config/settings.json ]; then
    echo "Creating default configuration..."
    # Use venv if available
    if [ -d "venv" ] && [ -f "venv/bin/python" ]; then
        # Try to activate venv, fallback to direct venv Python
        if source venv/bin/activate 2>/dev/null && [ -n "$VIRTUAL_ENV" ]; then
            python -c "
from pathlib import Path
from dv2plex.config import Config
config = Config()
config.save_config()
print('Default configuration created.')
"
            deactivate
        else
            # Use venv Python directly
            venv/bin/python -c "
from pathlib import Path
from dv2plex.config import Config
config = Config()
config.save_config()
print('Default configuration created.')
"
        fi
    else
        python3 -c "
from pathlib import Path
from dv2plex.config import Config
config = Config()
config.save_config()
print('Default configuration created.')
"
    fi
    echo "✓ Configuration created: dv2plex/config/settings.json"
else
    echo "✓ Configuration already present"
fi

# 11. Real-ESRGAN note
echo ""
echo "11. Real-ESRGAN Setup..."
echo "⚠ Real-ESRGAN must be set up manually:"
echo "   1. Clone the repository: git clone https://github.com/xinntao/Real-ESRGAN.git"
echo "   2. Copy the entire folder to: dv2plex/bin/realesrgan/"
if [ -d "venv" ]; then
    echo "   3. Install dependencies: source venv/bin/activate && pip install -r dv2plex/bin/realesrgan/requirements.txt"
else
    echo "   3. Install dependencies: pip3 install -r dv2plex/bin/realesrgan/requirements.txt --user"
fi

# 12. Install and start systemd service
echo ""
echo "12. Installing systemd service (dv2plex.service)..."

if command -v systemctl >/dev/null 2>&1; then
    SERVICE_NAME="dv2plex"
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    WORKDIR="$(pwd)"
    USER_NAME="$(whoami)"

    sudo bash -c "cat > \"${SERVICE_FILE}\" <<EOF
[Unit]
Description=DV2Plex Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${WORKDIR}
ExecStart=/bin/bash -lc 'cd ${WORKDIR} && ./run.sh --no-gui'
Restart=on-failure
User=${USER_NAME}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF"

    sudo systemctl daemon-reload
    sudo systemctl enable "${SERVICE_NAME}"
    sudo systemctl restart "${SERVICE_NAME}"

    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        echo "✓ Service installiert und gestartet: ${SERVICE_NAME}"
    else
        echo "⚠ Service konnte nicht gestartet werden. Bitte Logs prüfen: sudo journalctl -u ${SERVICE_NAME}"
    fi
else
    echo "⚠ systemd nicht verfügbar. Bitte Service manuell einrichten."
fi

echo ""
echo "=========================================="
echo "Setup completed!"
echo "=========================================="
echo ""

# Check if script was sourced (not executed directly)
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    # Script was executed directly
    echo "⚠ WICHTIG: Das virtuelle Environment wurde erstellt, ist aber noch nicht aktiviert."
    echo ""
    echo "Um das venv zu aktivieren, führen Sie einen der folgenden Befehle aus:"
    echo "  source venv/bin/activate"
    echo "  . venv/bin/activate"
    echo ""
    echo "Oder rufen Sie das Setup-Skript mit 'source' auf, um das venv automatisch zu aktivieren:"
    echo "  source setup.sh"
    echo ""
else
    # Script was sourced
    if [ -d "venv" ] && [ -f "venv/bin/activate" ]; then
        echo "Aktiviere virtuelles Environment..."
        source venv/bin/activate
        echo "✓ Virtuelles Environment ist jetzt aktiviert!"
        echo ""
    fi
fi

echo "Next steps:"
echo "1. Connect your MiniDV camera via FireWire"
if [ "${BASH_SOURCE[0]}" != "${0}" ] && [ -d "venv" ]; then
    echo "2. Start the application with: ./run.sh"
    echo "3. Or: python -m dv2plex (venv ist bereits aktiviert)"
else
    echo "2. Aktivieren Sie das venv: source venv/bin/activate"
    echo "3. Start the application with: ./run.sh"
    echo "4. Or: python -m dv2plex"
fi
echo ""
