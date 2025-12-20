@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM Automatic Setup Script for DV2Plex (Windows)

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul

echo ==========================================
echo DV2Plex - Automatisches Setup (Windows)
echo ==========================================
echo.

REM 1. Python finden
set "PY_CMD="
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 set "PY_CMD=py -3"
if not defined PY_CMD (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 set "PY_CMD=python"
)
if not defined PY_CMD (
    echo Python 3.10+ wurde nicht gefunden. Bitte installieren.
    goto :fail
)

%PY_CMD% -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
    echo Python 3.10+ ist erforderlich.
    goto :fail
)
for /f "delims=" %%v in ('%PY_CMD% -c "import sys; print(sys.version.split()[0])"') do (
    echo Python Version: %%v
    goto :pip_check
)

:pip_check
echo.
echo 2. Pruefe pip...
%PY_CMD% -m pip --version >nul 2>nul
if errorlevel 1 (
    echo pip wurde nicht gefunden, versuche ensurepip...
    %PY_CMD% -m ensurepip --default-pip
)

:deps_check
echo.
echo 3. Pruefe ffmpeg...
call :check_ffmpeg

echo.
echo 4. Pruefe dvgrab...
where dvgrab >nul 2>nul
if errorlevel 1 (
    echo dvgrab nicht gefunden. FireWire-Capture muss ggf. separat eingerichtet werden.
) else (
    echo dvgrab gefunden.
)

echo.
echo 5. Erstelle/aktiviere virtuelles Environment...
if not exist "venv" (
    echo Erstelle virtuelles Environment...
    %PY_CMD% -m venv venv
    if errorlevel 1 (
        echo Virtuelles Environment konnte nicht erstellt werden.
        goto :fail
    )
)

call "%SCRIPT_DIR%venv\Scripts\activate.bat"
if not defined VIRTUAL_ENV (
    echo Aktivierung des virtuellen Environments fehlgeschlagen.
    goto :fail
)
echo venv aktiviert: %VIRTUAL_ENV%

echo.
echo 6. Installiere Python-Abhaengigkeiten...
python -m pip install --upgrade pip
if errorlevel 1 goto :fail

python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo 7. Erstelle Verzeichnisse...
for %%d in ("dv2plex\DV_Import" "dv2plex\logs" "dv2plex\config" "dv2plex\PlexMovies") do (
    if not exist %%~d mkdir %%~d
)

echo.
echo 8. FireWire-Hinweis...
echo Stelle sicher, dass IEEE 1394/FireWire-Treiber unter Windows installiert sind.

echo.
echo 9. FireWire-Test (falls dvgrab verfuegbar)...
where dvgrab >nul 2>nul
if not errorlevel 1 (
    dvgrab --list
) else (
    echo dvgrab nicht verfuegbar, ueberspringe Test.
)

echo.
echo 10. Erzeuge Standardkonfiguration (falls noetig)...
if not exist "dv2plex\config\settings.json" (
    python -c "from dv2plex.config import Config; Config().save_config(); print('Default configuration created.')"
) else (
    echo Konfiguration bereits vorhanden.
)

echo.
echo ==========================================
echo Setup abgeschlossen!
echo ==========================================
echo.
echo Naechste Schritte:
echo 1. Falls das venv nicht mehr aktiv ist: call venv\Scripts\activate.bat
echo 2. Anwendung starten: run.bat
echo 3. Oder: python -m dv2plex

popd >nul
exit /b 0

:fail
echo.
echo Setup abgebrochen wegen eines Fehlers.
popd >nul
exit /b 1

:check_ffmpeg
where ffmpeg >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo ffmpeg gefunden.
    exit /b 0
)
echo ffmpeg wurde nicht gefunden.
where choco >nul 2>nul
if %ERRORLEVEL% EQU 0 goto :install_ffmpeg_choco
echo Chocolatey nicht gefunden. Bitte ffmpeg manuell installieren (z.B. https://www.gyan.dev/ffmpeg/).
exit /b 0

:install_ffmpeg_choco
set "FFMPEG_CHOICE="
set /p FFMPEG_CHOICE=ffmpeg mit Chocolatey installieren? [y/N]:
if /I "%FFMPEG_CHOICE%"=="Y" (
    choco install -y ffmpeg
) else (
    echo ffmpeg wird uebersprungen.
)
exit /b 0

