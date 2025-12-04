@echo off
REM DV2Plex Start-Skript

REM Aktiviere Virtual Environment falls vorhanden
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Starte Anwendung
python start.py

pause

