# DV2Plex - Benutzer-Anleitung

## Erste Schritte

### 1. Voraussetzungen

- Windows 10/11
- MiniDV-Camcorder mit FireWire-Anschluss
- FireWire-Kabel (IEEE 1394)
- FireWire-Karte/Adapter (falls nicht im PC vorhanden)

### 2. Installation

1. **Python installieren** (falls noch nicht vorhanden)
   - Lade Python 3.10+ von https://www.python.org/
   - Wichtig: Bei Installation "Add Python to PATH" aktivieren

2. **Projekt-Dependencies installieren**
   ```bash
   pip install -r requirements.txt
   ```

3. **ffmpeg hinzufügen**
   - Lade ffmpeg von https://ffmpeg.org/download.html
   - Kopiere `ffmpeg.exe` nach `dv2plex/bin/ffmpeg.exe`

4. **Real-ESRGAN hinzufügen**
   - Klone Real-ESRGAN Repository: `git clone https://github.com/xinntao/Real-ESRGAN.git`
   - Kopiere den **gesamten** Real-ESRGAN-Ordner nach `dv2plex/bin/realesrgan/`
   - Die Struktur muss sein: `dv2plex/bin/realesrgan/inference_realesrgan_video.py`
   - Installiere Real-ESRGAN Dependencies:
     ```bash
     pip install -r requirements.txt
     ```
   - Modelle werden bei Bedarf automatisch heruntergeladen

### 3. Kamera konfigurieren

1. **Kamera anschließen**
   - FireWire-Kabel verbinden
   - Kamera einschalten
   - Windows sollte die Kamera erkennen

2. **Device-Namen finden**
   - Führe `setup_device.bat` aus
   - Suche in der Ausgabe nach dem Namen deiner Kamera
   - Beispiel: `"JVC GR-D245"` (mit Anführungszeichen)

3. **Device-Namen eintragen**
   - Starte die Anwendung einmal (erstellt Konfigurationsdatei)
   - Öffne `dv2plex/config/settings.json`
   - Trage den Device-Namen unter `"dshow_video_device"` ein:
   ```json
   {
     "device": {
       "dshow_video_device": "JVC GR-D245"
     }
   }
   ```

## Verwendung

### 1. Anwendung starten

```bash
python -m dv2plex.app
```

oder

```bash
run.bat
```

### 2. Erste Schritte in der Anwendung

#### a) Plex-Ordner konfigurieren
- Klicke auf "Plex Movies Ordner wählen"
- Wähle deinen Plex-Movies-Root-Ordner (z.B. `D:\Plex\Movies`)

#### b) Preview testen
- Klicke auf "Preview Start"
- Du solltest das Live-Bild der Kamera sehen
- Falls nicht: Prüfe FireWire-Verbindung und Device-Name

### 3. Kassette digitalisieren

#### Schritt 1: Kassette vorbereiten
- Kassette in die Kamera einlegen
- Optional: Preview starten, um Position zu prüfen

#### Schritt 2: Film-Informationen eingeben
- **Titel**: z.B. "Las Vegas Urlaub"
- **Jahr**: z.B. "2001"

#### Schritt 3: Aufnahme starten
- Klicke auf "Aufnahme Start"
- **Wichtig**: Die App fragt dich, die Kassette vorzubereiten
- Spule die Kassette an den Anfang
- Drücke Play auf der Kamera
- Klicke OK in der Anwendung

#### Schritt 4: Aufnahme überwachen
- Die Aufnahme läuft jetzt
- Du kannst den Status im Log-Bereich verfolgen
- Die Aufnahme stoppt automatisch am Bandende
- Oder: Klicke "Aufnahme Stop" zum manuellen Stoppen

#### Schritt 5: Postprocessing
- Nach der Aufnahme startet automatisch das Postprocessing:
  1. **Merge**: Alle Parts werden zu einem Film zusammengefügt
  2. **Upscaling**: Film wird auf 4K hochskaliert (kann lange dauern!)
  3. **Export**: Film wird nach Plex kopiert (wenn aktiviert)

- Falls automatisches Postprocessing deaktiviert ist:
  - Klicke auf "Postprocessing starten"

### 4. Ergebnis

Nach erfolgreichem Postprocessing findest du:

- **Roh-Aufnahme**: `dv2plex/DV_Import/[Filmname (Jahr)]/LowRes/movie_merged.avi`
- **4K-Video**: `dv2plex/DV_Import/[Filmname (Jahr)]/HighRes/[Filmname (Jahr)]_4k.mp4`
- **Plex-Export**: `[Plex-Ordner]/[Filmname (Jahr)]/[Filmname (Jahr)].mp4`

## Einstellungen

### Konfigurationsdatei

Die Einstellungen werden in `dv2plex/config/settings.json` gespeichert.

### Wichtige Einstellungen

#### Automatisches Postprocessing
```json
{
  "capture": {
    "auto_merge": true,      // Automatisch mergen nach Capture
    "auto_upscale": true,    // Automatisch upscalen nach Merge
    "auto_export": false     // Automatisch nach Plex exportieren
  }
}
```

#### Upscaling-Profil
- Wähle im Dropdown-Menü das gewünschte Profil:
  - **RealESRGAN 4x HQ**: Beste Qualität, langsam
  - **RealESRGAN 4x Balanced**: Gute Balance zwischen Qualität und Geschwindigkeit
  - **RealESRGAN 4x Fast**: Schneller, gute Qualität
  - **RealESRGAN 2x**: 2x Upscaling (schneller)

## Troubleshooting

### "ffmpeg nicht gefunden"
- Prüfe ob `ffmpeg.exe` in `dv2plex/bin/` liegt
- Prüfe den Pfad in `settings.json`

### "Real-ESRGAN nicht gefunden"
- Stelle sicher, dass `inference_realesrgan_video.py` in `dv2plex/bin/realesrgan/` liegt
- Klone das Repository: `git clone https://github.com/xinntao/Real-ESRGAN.git`
- Installiere Dependencies: `pip install -r requirements.txt`
- Modelle werden bei Bedarf automatisch heruntergeladen

### "Kein Signal von Kamera"
- Prüfe FireWire-Verbindung
- Kamera eingeschaltet?
- Device-Name korrekt in `settings.json`?
- Führe `setup_device.bat` aus, um verfügbare Geräte zu sehen

### Preview funktioniert nicht
- Prüfe FireWire-Treiber
- Versuche Kamera neu anzuschließen
- Prüfe ob Device-Name korrekt ist

### Aufnahme startet nicht
- Prüfe ob Kamera auf Play steht
- Prüfe FireWire-Verbindung
- Prüfe Log-Ausgabe für Fehlermeldungen

### Upscaling dauert sehr lange
- Das ist normal! 4K-Upscaling kann 10-20 Minuten pro Minute Video dauern
- Abhängig von GPU und gewähltem Profil
- Prüfe GPU-Auslastung im Task Manager

### "Datei existiert bereits" beim Export
- Die Datei existiert bereits im Plex-Ordner
- Lösche die alte Datei manuell oder ändere den Dateinamen

## Tipps

### Mehrere Parts aufnehmen
- Wenn du eine Kassette in mehreren Teilen aufnimmst:
  - Starte einfach mehrere Aufnahmen nacheinander
  - Die App nummeriert automatisch: `part_001.avi`, `part_002.avi`, etc.
  - Beim Merge werden alle Parts automatisch zusammengefügt

### Nur bestimmte Teile verarbeiten
- Deaktiviere `auto_merge` oder `auto_upscale` in den Einstellungen
- Starte dann manuell das Postprocessing, wenn du bereit bist

### Schnellere Verarbeitung
- Verwende "RealESRGAN 4x Fast" statt "HQ"
- Reduziere CRF-Wert im Profil (z.B. 17 → 20)
- Ändere Preset von "veryslow" zu "medium"

### Bessere Qualität
- Verwende "RealESRGAN 4x HQ"
- Erhöhe CRF-Wert (z.B. 20 → 17)
- Verwende "veryslow" Preset

## Support

Bei Problemen:
1. Prüfe die Log-Dateien in `dv2plex/logs/`
2. Prüfe die Konfiguration in `dv2plex/config/settings.json`
3. Stelle sicher, dass alle Tools (ffmpeg, Real-ESRGAN) korrekt installiert sind

