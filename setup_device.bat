@echo off
REM Helper script to find FireWire devices on Windows

echo Suche nach FireWire-Geraeten...
echo.

where dvgrab >nul 2>nul
if %ERRORLEVEL%==0 (
    dvgrab --list
) else (
    echo dvgrab wurde nicht gefunden.
    echo Unter Windows ist dvgrab ggf. nicht verfuegbar.
    echo Pruefe den Geraetemanager (IEEE 1394-Hostcontroller / Bildverarbeitungsgeraete)
    echo und installiere passende FireWire-Treiber.
)

echo.
echo Notiere den Pfad bzw. das Geraet im Geraetemanager, falls eine manuelle
echo Konfiguration noetig ist. Die automatische Erkennung funktioniert meist ohne Anpassung.


