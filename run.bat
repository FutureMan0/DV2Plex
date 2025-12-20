@echo off
setlocal EnableDelayedExpansion
REM DV2Plex Start Script for Windows with dependency check

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul

call :check_dep ffmpeg
call :check_dep dvgrab
echo.

set "VENV_PY=%SCRIPT_DIR%venv\Scripts\python.exe"

if exist "%VENV_PY%" (
    "%VENV_PY%" "%SCRIPT_DIR%start.py" %*
) else (
    python "%SCRIPT_DIR%start.py" %*
)

set "EXITCODE=%ERRORLEVEL%"
popd >nul
exit /b %EXITCODE%

:check_dep
set "CMD=%~1"
where "%CMD%" >nul 2>nul
if %ERRORLEVEL%==0 (
    echo %CMD% vorhanden
) else (
    if /I "%CMD%"=="dvgrab" (
        echo dvgrab nicht gefunden. FireWire-Capture muss ggf. separat eingerichtet werden.
    ) else (
        call :ask_install "%CMD%"
    )
)
exit /b 0

:ask_install
set "PKG=%~1"
echo %PKG% fehlt.
where choco >nul 2>nul
if %ERRORLEVEL%==0 (
    set /p ANSWER=Mit Chocolatey installieren? [y/N]:
    if /I "!ANSWER!"=="Y" (
        choco install -y "%PKG%"
    ) else (
        echo %PKG% wird uebersprungen.
    )
) else (
    echo Chocolatey nicht gefunden. Bitte %PKG% manuell installieren.
)
exit /b 0


