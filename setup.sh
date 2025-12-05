#!/bin/bash
# Automatic Setup Script für DV2Plex (Linux)

set -e

echo "=========================================="
echo "DV2Plex - Automatic Setup (Linux)"
echo "=========================================="
echo ""

# Prüfe ob wir root sind (für Paket-Installation)
NEED_SUDO=false

# Funktion zum Prüfen von Kommandos
check_command() {
    if command -v "$1" &> /dev/null; then
        echo "✓ $1 gefunden"
        return 0
    else
        echo "✗ $1 nicht gefunden"
        return 1
    fi
}

# Funktion zum Installieren von Paketen
install_package() {
    if [ -f /etc/debian_version ]; then
        # Debian/Ubuntu
        echo "Installiere $1 mit apt..."
        sudo apt-get update
        sudo apt-get install -y "$1"
    elif [ -f /etc/redhat-release ]; then
        # RedHat/CentOS/Fedora
        echo "Installiere $1 mit yum/dnf..."
        if command -v dnf &> /dev/null; then
            sudo dnf install -y "$1"
        else
            sudo yum install -y "$1"
        fi
    elif [ -f /etc/arch-release ]; then
        # Arch Linux
        echo "Installiere $1 mit pacman..."
        sudo pacman -S --noconfirm "$1"
    else
        echo "Unbekannte Distribution. Bitte installieren Sie $1 manuell."
        return 1
    fi
}

# 1. Prüfe Python
echo "1. Prüfe Python..."
if ! check_command python3; then
    echo "Python 3 nicht gefunden. Installiere..."
    install_package python3
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
echo "Python Version: $PYTHON_VERSION"

# Prüfe Python 3.10+
if python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "✓ Python 3.10+ gefunden"
else
    echo "✗ Python 3.10+ erforderlich. Bitte aktualisieren Sie Python."
    exit 1
fi

# 2. Prüfe pip
echo ""
echo "2. Prüfe pip..."
if ! check_command pip3; then
    echo "pip3 nicht gefunden. Installiere..."
    install_package python3-pip
fi

# 3. Prüfe dvgrab
echo ""
echo "3. Prüfe dvgrab..."
if ! check_command dvgrab; then
    echo "dvgrab nicht gefunden. Installiere..."
    if [ -f /etc/debian_version ]; then
        install_package dvgrab
    elif [ -f /etc/redhat-release ]; then
        if command -v dnf &> /dev/null; then
            sudo dnf install -y dvgrab
        else
            echo "dvgrab ist möglicherweise nicht in den Standard-Repositories."
            echo "Bitte installieren Sie dvgrab manuell."
        fi
    elif [ -f /etc/arch-release ]; then
        install_package dvgrab
    else
        echo "Bitte installieren Sie dvgrab manuell für Ihre Distribution."
    fi
fi

# 4. Prüfe ffmpeg
echo ""
echo "4. Prüfe ffmpeg..."
if ! check_command ffmpeg; then
    echo "ffmpeg nicht gefunden. Installiere..."
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
        echo "Bitte installieren Sie ffmpeg manuell für Ihre Distribution."
    fi
fi

# 5. Prüfe FireWire-Treiber
echo ""
echo "5. Prüfe FireWire-Treiber..."
if [ -f /etc/debian_version ]; then
    if ! dpkg -l | grep -q libraw1394; then
        echo "FireWire-Treiber nicht gefunden. Installiere..."
        install_package libraw1394-dev
        install_package libavc1394-dev
    else
        echo "✓ FireWire-Treiber gefunden"
    fi
elif [ -f /etc/redhat-release ]; then
    if ! rpm -qa | grep -q libraw1394; then
        echo "FireWire-Treiber nicht gefunden. Installiere..."
        if command -v dnf &> /dev/null; then
            sudo dnf install -y libraw1394-devel libavc1394-devel
        else
            sudo yum install -y libraw1394-devel libavc1394-devel
        fi
    else
        echo "✓ FireWire-Treiber gefunden"
    fi
elif [ -f /etc/arch-release ]; then
    if ! pacman -Q libraw1394 &> /dev/null; then
        echo "FireWire-Treiber nicht gefunden. Installiere..."
        install_package libraw1394
        install_package libavc1394
    else
        echo "✓ FireWire-Treiber gefunden"
    fi
else
    echo "Bitte installieren Sie libraw1394 und libavc1394 manuell."
fi

# 6. Installiere Python-Dependencies
echo ""
echo "6. Installiere Python-Dependencies..."

# Prüfe ob python3-venv installiert ist
if ! python3 -m venv --help &> /dev/null; then
    echo "python3-venv nicht gefunden. Installiere..."
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
        echo "⚠ Bitte installieren Sie python3-venv manuell"
    fi
fi

# Erstelle virtuelles Environment falls nicht vorhanden
if [ ! -d "venv" ]; then
    echo "Erstelle virtuelles Environment..."
    if python3 -m venv venv; then
        echo "✓ Virtuelles Environment erstellt"
    else
        echo "✗ Fehler beim Erstellen des virtuellen Environments"
        echo "Versuche Installation mit --user Flag..."
        pip3 install -r requirements.txt --user --break-system-packages || {
            echo "✗ Installation fehlgeschlagen. Bitte manuell installieren:"
            echo "  sudo apt install python3-venv"
            echo "  python3 -m venv venv"
            echo "  source venv/bin/activate"
            echo "  pip install -r requirements.txt"
        }
        exit 0  # Weiter mit Setup auch wenn venv fehlschlägt
    fi
fi

# Aktiviere venv und installiere Dependencies (falls venv existiert)
if [ -d "venv" ] && [ -f "venv/bin/activate" ]; then
    echo "Aktiviere virtuelles Environment und installiere Dependencies..."
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    deactivate
    echo "✓ Python-Dependencies installiert"
else
    echo "⚠ Virtuelles Environment konnte nicht erstellt werden"
    echo "Versuche Installation mit --user Flag..."
    pip3 install -r requirements.txt --user --break-system-packages || {
        echo "✗ Installation fehlgeschlagen. Bitte manuell installieren:"
        echo "  sudo apt install python3-venv"
        echo "  python3 -m venv venv"
        echo "  source venv/bin/activate"
        echo "  pip install -r requirements.txt"
    }
fi

# 7. Erstelle notwendige Verzeichnisse
echo ""
echo "7. Erstelle Verzeichnisse..."
mkdir -p dv2plex/DV_Import
mkdir -p dv2plex/logs
mkdir -p dv2plex/config
mkdir -p dv2plex/PlexMovies

# 8. Konfiguriere FireWire-Berechtigungen
echo ""
echo "8. Konfiguriere FireWire-Berechtigungen..."
if [ -e /dev/raw1394 ]; then
    # Prüfe ob Benutzer bereits in der video-Gruppe ist
    if groups | grep -q video; then
        echo "✓ Benutzer ist bereits in der video-Gruppe"
    else
        echo "Füge Benutzer zur video-Gruppe hinzu..."
        sudo usermod -a -G video "$USER"
        echo "⚠ Bitte melden Sie sich ab und wieder an, damit die Gruppenänderung wirksam wird."
    fi
    
    # Setze Berechtigungen (falls nötig)
    if [ -w /dev/raw1394 ]; then
        echo "✓ Berechtigungen für /dev/raw1394 sind korrekt"
    else
        echo "⚠ /dev/raw1394 ist nicht schreibbar. Möglicherweise müssen Sie sich neu anmelden."
    fi
else
    echo "⚠ /dev/raw1394 nicht gefunden. Bitte verbinden Sie ein FireWire-Gerät."
fi

# 9. Teste FireWire-Verbindung
echo ""
echo "9. Teste FireWire-Verbindung..."
if command -v dvgrab &> /dev/null; then
    if dvgrab --list 2>&1 | grep -q "Device"; then
        echo "✓ FireWire-Gerät erkannt:"
        dvgrab --list
    else
        echo "⚠ Kein FireWire-Gerät gefunden. Bitte verbinden Sie eine Kamera."
    fi
else
    echo "⚠ dvgrab nicht verfügbar, kann FireWire-Verbindung nicht testen."
fi

# 10. Erstelle Standard-Konfiguration falls nicht vorhanden
echo ""
echo "10. Erstelle Standard-Konfiguration..."
if [ ! -f dv2plex/config/settings.json ]; then
    echo "Erstelle Standard-Konfiguration..."
    # Verwende venv falls vorhanden
    if [ -d "venv" ]; then
        source venv/bin/activate
        python -c "
from pathlib import Path
from dv2plex.config import Config
config = Config()
config.save_config()
print('Standard-Konfiguration erstellt.')
"
        deactivate
    else
        python3 -c "
from pathlib import Path
from dv2plex.config import Config
config = Config()
config.save_config()
print('Standard-Konfiguration erstellt.')
"
    fi
    echo "✓ Konfiguration erstellt: dv2plex/config/settings.json"
else
    echo "✓ Konfiguration bereits vorhanden"
fi

# 11. Real-ESRGAN Hinweis
echo ""
echo "11. Real-ESRGAN Setup..."
echo "⚠ Real-ESRGAN muss manuell eingerichtet werden:"
echo "   1. Klone das Repository: git clone https://github.com/xinntao/Real-ESRGAN.git"
echo "   2. Kopiere den gesamten Ordner nach: dv2plex/bin/realesrgan/"
if [ -d "venv" ]; then
    echo "   3. Installiere Dependencies: source venv/bin/activate && pip install -r dv2plex/bin/realesrgan/requirements.txt"
else
    echo "   3. Installiere Dependencies: pip3 install -r dv2plex/bin/realesrgan/requirements.txt --user"
fi

echo ""
echo "=========================================="
echo "Setup abgeschlossen!"
echo "=========================================="
echo ""
echo "Nächste Schritte:"
echo "1. Verbinden Sie Ihre MiniDV-Kamera über FireWire"
echo "2. Starten Sie die Anwendung mit: ./run.sh"
echo "3. Oder: python3 -m dv2plex.app"
echo ""

