@echo off
REM Hilfsskript zum Finden des DirectShow-Device-Namens

echo Suche nach DirectShow-Geraten...
echo.

if exist "dv2plex\bin\ffmpeg.exe" (
    dv2plex\bin\ffmpeg.exe -list_devices true -f dshow -i dummy 2>&1 | findstr /i "video"
) else (
    echo ffmpeg.exe nicht gefunden in dv2plex\bin\
    echo Bitte ffmpeg.exe in dv2plex\bin\ kopieren.
)

echo.
echo Suchen Sie nach dem Namen Ihrer Kamera (z.B. "JVC GR-D245")
echo und tragen Sie diesen in die Konfiguration ein.
pause

