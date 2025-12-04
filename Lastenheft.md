# DV2Plex - Projekt-Blueprint / Lastenheft

## A. Ziel & Rahmenbedingungen

### Systemanforderungen
- **Betriebssystem:** Windows
- **Quelle:** MiniDV-Camcorder über FireWire (z.B. JVC GR-D245)
- **Eingebettete Tools:**
  - **ffmpeg** (als EXE im Projektordner)
  - **Video2X** (kompletter Ordner im Projektordner, nicht nur eine EXE)
- **Kein dvcontrol.exe** (manuelle Kamera-Bedienung)

### Manuelle Bedienung
Die Kamera wird zunächst **manuell** bedient:
- Kassette einlegen
- Nach Bedarf zurückspulen
- Play drücken, wenn die App es anzeigt

### Ziel pro Kassette
- **1 Film in Plex**
- Format: `Titel (Jahr)` als Ordner- und Dateiname in der Plex-Movies-Library

---

## B. Komponenten / Bausteine der Anwendung

Die Anwendung besteht logisch aus 5 Haupt-Bausteinen:

### 1. GUI (PySide6-Frontend)
- Darstellung, Eingaben (Titel/Jahr), Buttons, Status
- Live-Preview der Kamera
- Fortschrittsanzeige

### 2. Capture-Engine (ffmpeg)
- Liest das DV-Signal über DirectShow
- Schreibt einen oder mehrere Roh-Datei-Parts im LowRes-Ordner

### 3. Merge-Engine (ffmpeg concat)
- Fügt alle `part_*.avi` zu einem einzigen `movie_merged.avi` zusammen

### 4. Upscale-Engine (Video2X)
- Nimmt `movie_merged.avi` als Input
- Ruft Video2X als CLI mit konfigurierbarem Profil auf (RealESRGAN, Anime4K, etc.)
- Erzeugt eine 4K-Datei als HighRes

### 5. Plex-Exporter
- Benennt die HighRes-Datei passend (`Titel (Jahr).mp4`)
- Kopiert sie in die Plex-Movie-Library-Struktur

**Alle Komponenten laufen innerhalb einer Anwendung**, die sich selbst alles holt, was sie braucht (ffmpeg, Video2X) aus ihrem eigenen Unterordner.

---

## C. Projektstruktur (Ordner & Dateien)

### 1. Top-Level

```
DV2Plex/
  dv2plex/           ← das eigentliche Programm-Paket
  venv/              ← optionale Python-Umgebung (für lokalen Gebrauch)
  run.bat            ← Start-Skript (optional)
  README.md          ← Projekt-Dokumentation
  Lastenheft.md      ← dieses Dokument
```

### 2. Programm-Paket `dv2plex/`

```
dv2plex/
  __init__.py        ← Paket-Info
  app.py             ← Hauptprogramm (GUI + Logik)
  config.py          ← Konfiguration (Pfade, Voreinstellungen)
  capture.py         ← Capture-Engine (ffmpeg-Wrapper)
  merge.py           ← Merge-Engine (ffmpeg concat)
  upscale.py         ← Upscale-Engine (Video2X-Wrapper)
  plex_export.py     ← Plex-Exporter
  bin/               ← alle externen Programme
  resources/         ← Icons, evtl. Designs
  config/            ← Konfigurationsdateien
  DV_Import/         ← hier liegen deine digitalisierten Tapes
  PlexMovies/        ← optionaler Standard-Plex-Root (kann überschrieben werden)
```

### 3. Unterordner `bin/` (Tools)

```
dv2plex/bin/
  ffmpeg.exe
  video2x/           ← kompletter Video2X-Ordner, genauso wie entpackt
    video2x.exe
    (alle DLLs, Models, Configs von Video2X)
  (optional später) dvcontrol/
```

**Wichtig:**
- **Video2X braucht den ganzen Ordner** → der vollständige Video2X-Ordner wird in `dv2plex/bin/video2x/` kopiert
- Die App kennt den Pfad zur Video2X-EXE relativ: `…/bin/video2x/video2x.exe`
- ffmpeg liegt direkt in `bin/`: `…/bin/ffmpeg.exe`

### 4. Arbeitsordner für Tapes

In `dv2plex/DV_Import/` legt die App für **jedes Tape / jeden Film** einen eigenen Ordner an:

```
dv2plex/DV_Import/
  Las Vegas Urlaub (2001)/
    LowRes/
      part_001.avi
      part_002.avi
      ...
      movie_merged.avi
    HighRes/
      Las Vegas Urlaub (2001)_4k.mp4
```

### 5. Plex-Root im Projekt (optional)

Standardmäßig kann die App einen Default-Plex-Root im Projekt haben:

```
dv2plex/PlexMovies/
  Las Vegas Urlaub (2001)/
    Las Vegas Urlaub (2001).mp4
```

Dieser Pfad kann später im UI auf den echten Plex-Movies-Ordner umgestellt werden (z.B. `D:\Plex\Movies`).

---

## D. Wie das Programm arbeitet (Ablauf im Detail)

### 1. Start & Konfiguration

**Beim Start:**
- Das Programm ermittelt seinen **eigenen Ordner** (wo `app.py` liegt)
- Definiert die Pfade:
  - ffmpeg: `…/bin/ffmpeg.exe`
  - Video2X: `…/bin/video2x/video2x.exe`
  - DV_IMPORT_ROOT: `…/DV_Import`
  - PLEX_MOVIES_ROOT: standardmäßig `…/PlexMovies` (später über Einstellungen änderbar)

**Einmalige Konfiguration:**
- DirectShow-Device-Namen der Kamera herausfinden:
  - Im Terminal: `ffmpeg -list_devices true -f dshow -i dummy`
  - In der Liste den Eintrag der JVC finden, z.B. `"JVC GR-D245"`
  - Dieser String wird als Konfiguration abgelegt

### 2. GUI-Aufbau (Benutzeroberfläche)

Das Hauptfenster zeigt:

**1. Oben: Filminformationen**
- Textfeld „Titel" – was später in Plex erscheint, z.B. „Las Vegas Urlaub"
- Textfeld „Jahr" – z.B. „2001"

**2. Mitte: Live-Preview**
- Großes Feld, in dem das Live-Bild der Kamera angezeigt wird

**3. Unten: Buttons**
- „Preview Start" / „Preview Stop"
- „Aufnahme Start" / „Aufnahme Stop"
- „Plex Movies Ordner wählen" (öffnet einen Dialog für den Plex-Movies-Root)
- „Postprocessing starten" (optional, falls nicht automatisch)

**4. Statusbereich**
- Text: „Bereit.", „Preview läuft…", „Aufnahme läuft…", „Upscaling…" usw.
- Fortschrittsbalken (busy-Spinner für länger laufende Schritte)

---

## E. Technischer Ablauf pro Kassette

### Phase 1: Live-Preview

**Ziel:** Überprüfung, ob Kamera und Verbindung funktionieren.

**Ablauf:**
- Beim Klick auf **„Preview Start"** startet die App intern einen ffmpeg-Prozess im „Bildstrom"-Modus:
  - Input: `-f dshow -i video=KameraName`
  - Output: MJPEG-Stream über Stdout
- Ein Hintergrund-Thread:
  - Liest diesen Stream
  - Konvertiert die JPEG-Frames in Bilder
  - Zeigt sie regelmäßig im Preview-Feld
- Bei „Preview Stop" wird dieser Prozess beendet

**Wichtig:** In dieser Phase wird die Kassette manuell bedient (zurückspulen, zum Anfang spulen etc.), bis alles zufriedenstellend ist.

---

### Phase 2: Start Aufnahme

**Vorbereitung:**
1. **Titel** und **Jahr** eingeben:
   - z.B. Titel: `Las Vegas Urlaub`
   - Jahr: `2001`
2. Klick auf **„Aufnahme Start"**

**Hintergrund-Prozess:**
1. Die App kombiniert Titel und Jahr zu einem Filmnamen:
   - `Las Vegas Urlaub (2001)`

2. Sie erstellt Arbeitsordner:
   - `DV_Import/Las Vegas Urlaub (2001)/LowRes/`
   - `DV_Import/Las Vegas Urlaub (2001)/HighRes/`

3. Sie legt für den ersten Aufnahmeblock einen Dateinamen fest:
   - `LowRes/part_001.avi`

4. **Wichtig ohne dvcontrol:**
   - Die App zeigt im Status:
     „Bitte Kassette an den Anfang spulen und auf Play drücken, dann OK…"
   - Benutzer bedient die Kamera manuell
   - Wenn alles läuft, startet die App **ffmpeg** in einem Aufnahmeprozess:
     - Input: `-f dshow -i video=DeinKameraName`
     - Output: `-c copy LowRes/part_001.avi`

5. Diese Aufnahme läuft, bis:
   - **„Aufnahme Stop"** geklickt wird, **oder**
   - die Kassette am Ende ist und das Signal abreißt (dann beendet ffmpeg sich selbst)

**Dateiverwaltung:**
- Die App merkt sich, dass `part_001.avi` erfolgreich aufgezeichnet wurde
- Falls nochmal gestartet wird (z.B. für eine zweite Hälfte), kann sie `part_002.avi`, `part_003.avi` usw. erzeugen
- Im einfachsten Fall gibt es **pro Kassette genau 1 Datei**

---

### Phase 3: Aufnahme beendet

**Wenn die Aufnahme fertig ist (manuell oder Bandende):**
- ffmpeg stoppt
- Die App:
  - Beendet den Capture-Thread
  - Zeigt im Status: „Aufnahme beendet. Mergen wird vorbereitet."

**Optional:** Falls keine Automatik gewünscht ist, kann ein extra Button „Postprocessing starten" die nächsten Schritte anstoßen.

---

### Phase 4: Merge der Aufnahme-Dateien (LowRes → ein Film)

**Ziel:** Egal ob 1 oder mehrere `part_*.avi`, am Ende wird **einen** Roh-Film erzeugt.

**Ablauf:**
1. Die App durchsucht den `LowRes`-Ordner nach allen Dateien mit Muster `part_*.avi` und sortiert sie

2. **Wenn genau 1 Datei:**
   - Diese wird einfach **kopiert/umbenannt** zu `movie_merged.avi`

3. **Wenn mehrere Dateien:**
   - Die App erzeugt eine Liste im ffmpeg-Format:
     - Datei `list.txt` im `LowRes`-Ordner, Inhalt:
       ```
       file 'part_001.avi'
       file 'part_002.avi'
       ...
       ```
   - Dann ruft sie ffmpeg mit dem concat-Modus auf:
     - Input: `-f concat -safe 0 -i list.txt`
     - Output: `-c copy movie_merged.avi`

4. **Ergebnis:**
   - `DV_Import/Las Vegas Urlaub (2001)/LowRes/movie_merged.avi`
   - ist jetzt der komplette DV-Film in Originalqualität

---

### Phase 5: Upscaling mit Video2X

**Wichtig:** Video2X läuft aus seinem eingebetteten Ordner:
`…/bin/video2x/video2x.exe`
und erwartet, dass der komplette Video2X-Ordner vorhanden ist.

**Ablauf:**
1. Die App baut den Pfad zu `video2x.exe` auf Basis ihres eigenen Ordners

2. Wählt ein Profil (z.B. Hardcoded oder über UI):
   - **RealESRGAN 4x Upscale:**
     - `-i movie_merged.avi`
     - `-o "Las Vegas Urlaub (2001)_4k.mp4"`
     - `-p realesrgan`
     - `-s 4`
     - `--realesrgan-model realesrgan-plus` (oder gewünschtes Modell)
     - Optional Encoder-Feintuning:
       - `-c libx264rgb`
       - `-e crf=17`
       - `-e preset=veryslow`
       - `-e tune=film`
   - **oder libplacebo/Anime4K:**
     - `-p libplacebo`
     - `-w 3840 -h 2160`
     - `--libplacebo-shader anime4k-v4-a+a`
     - plus Encoderoptionen

3. **Input-Datei:**
   - `LowRes/movie_merged.avi`

4. **Output-Datei:**
   - `HighRes/Las Vegas Urlaub (2001)_4k.mp4`

**Fortschrittsanzeige:**
- Das kann je nach GPU/CPU relativ lange dauern
- Die App zeigt:
  - Fortschritt (falls später Parsing implementiert wird), oder
  - „Upscaling läuft…" mit einem „busy"-Indikator

**Ergebnis dieser Phase:**
`DV_Import/Las Vegas Urlaub (2001)/HighRes/Las Vegas Urlaub (2001)_4k.mp4`

---

### Phase 6: Export in Plex als Film

**Plex-Standard-Library-Struktur für Filme:**
```
PLEX_MOVIES_ROOT/
  Filmname (Jahr)/
    Filmname (Jahr).mp4
```

**Ablauf:**
1. Der Plex-Movies-Root (`PLEX_MOVIES_ROOT`) kann in den Einstellungen der App gesetzt werden, z.B.:
   - `D:\Plex\Movies`

2. Für `Las Vegas Urlaub (2001)` erzeugt die App:
   - **Zielordner:**
     `D:\Plex\Movies\Las Vegas Urlaub (2001)\`
   - **Zieldatei:**
     `D:\Plex\Movies\Las Vegas Urlaub (2001)\Las Vegas Urlaub (2001).mp4`

3. Sie kopiert die HighRes-Datei:
   - **Quelle:**
     `DV_Import/Las Vegas Urlaub (2001)/HighRes/Las Vegas Urlaub (2001)_4k.mp4`
   - **Ziel:**
     `D:\Plex\Movies\Las Vegas Urlaub (2001)\Las Vegas Urlaub (2001).mp4`

4. Plex wird bei der nächsten Library-Aktualisierung den Film anzeigen

---

## F. Konfiguration & Profile

### 1. Speicherung der Einstellungen

**Konfigurationsdatei** (z.B. JSON / INI) enthält:
- Pfad zum Plex-Movies-Root
- DirectShow-Device-Name
- Standard-Upscaling-Profil (z.B. RealESRGAN 4x)
- Encoderpräferenzen (CRF, Preset)

Diese Datei liegt z.B. in `dv2plex/config/` oder direkt neben `app.py`.

### 2. Upscaling-Profile

**Profil-Namen:**
- „RealESRGAN 4x HQ"
- „Anime4K 4K"
- „Schnell (niedrige Qualität)"

**Jedes Profil speichert:**
- Backend (`realesrgan` oder `libplacebo`)
- Parameter:
  - Skalierung / Zielauflösung
  - Modell / Shader
  - Encoder & -e Optionen

Im UI kann ein Dropdown „Upscaling-Profil" angeboten werden.

---

## G. Das Projekt „mobil" machen (auf anderen PCs nutzbar)

**Ziel:** Den ganzen Ordner **DV2Plex** auf eine andere Windows-Maschine kopieren und dort einfach loslegen.

### Variante 1: Portables Projekt mit Python

- Im Projekt einen `venv/`-Ordner mit Python + allen Libraries (PySide6, etc.)
- Ein kleines `run.bat`, das:
  - `venv\Scripts\activate` ausführt
  - dann `python -m dv2plex.app` startet

**Voraussetzungen:**
- Ziel-PC ist architekturkompatibel (64-bit)
- Gleiche oder passende Windows-Version (damit die Binaries laufen)

### Variante 2: Ein einzelnes EXE-Bundle (z.B. PyInstaller)

- Der „Build"-Prozess erzeugt eine `DV2Plex.exe`
- In der Build-Konfiguration wird angegeben, dass:
  - der komplette Ordner `dv2plex/bin/ffmpeg.exe`
  - und der komplette Ordner `dv2plex/bin/video2x/`
    in den Build integriert werden

**Ergebnis:**
```
DV2Plex_portable/
  DV2Plex.exe
  (evtl. data-Unterordner mit video2x und ffmpeg, vom Builder platziert)
```

- Nur diesen Ordner kopieren
- `DV2Plex.exe` starten
- Alles andere ist intern

**Hinweis:** Wie genau das gemacht wird, hängt vom verwendeten Builder ab (PyInstaller, cx_Freeze, etc.), aber das Konzept bleibt: die EXE **nutzt relative Pfade** zu ffmpeg und Video2X, die beim Bauen mit verpackt werden.

---

## H. Späteres Upgrade: Automatisches Rewind/Play

Falls später ein Tool wie `dvcontrol.exe` (oder etwas Ähnliches über DirectShow/AVC) eingebaut wird, muss das Konzept nicht geändert werden:

**Erweiterung:**
- „Beim Start der Aufnahme:
  - Kassette automatisch auf Anfang spulen
  - Play automatisch starten"

**Ablauf:**
- `rewind` aufrufen
- Einige Sekunden warten
- `play` aufrufen
- Dann ffmpeg starten

**Der restliche Workflow** (Merge, Upscaling, Plex) bleibt exakt gleich.

---

## I. Technische Details & Parameter

### DirectShow-Device-Erkennung

**Befehl zur Geräteauflistung:**
```bash
ffmpeg -list_devices true -f dshow -i dummy
```

**Erwartete Ausgabe:**
```
[dshow @ ...] "JVC GR-D245" (video)
```

**Konfiguration:**
- Device-Name wird in Konfigurationsdatei gespeichert
- Format: `"JVC GR-D245"` (mit Anführungszeichen, falls Leerzeichen enthalten)

### ffmpeg Capture-Parameter

**Basis-Kommando:**
```bash
ffmpeg -f dshow -i video="JVC GR-D245" -c copy output.avi
```

**Optionen:**
- `-f dshow`: DirectShow-Input
- `-i video="DeviceName"`: Video-Device
- `-c copy`: Stream-Kopie (keine Rekodierung)
- Output: AVI-Container (DV-kompatibel)

### ffmpeg Merge-Parameter

**Concat-Liste (`list.txt`):**
```
file 'part_001.avi'
file 'part_002.avi'
```

**Befehl:**
```bash
ffmpeg -f concat -safe 0 -i list.txt -c copy movie_merged.avi
```

**Optionen:**
- `-f concat`: Concat-Demuxer
- `-safe 0`: Erlaubt absolute Pfade
- `-c copy`: Stream-Kopie (keine Rekodierung)

### Video2X Parameter-Beispiele

**RealESRGAN 4x:**
```bash
video2x.exe -i input.avi -o output.mp4 -p realesrgan -s 4 --realesrgan-model realesrgan-plus -c libx264rgb -e crf=17 -e preset=veryslow -e tune=film
```

**Anime4K (libplacebo):**
```bash
video2x.exe -i input.avi -o output.mp4 -p libplacebo -w 3840 -h 2160 --libplacebo-shader anime4k-v4-a+a -c libx264rgb -e crf=17
```

**Parameter-Übersicht:**
- `-i`: Input-Datei
- `-o`: Output-Datei
- `-p`: Profil/Backend (`realesrgan`, `libplacebo`)
- `-s`: Skalierungsfaktor (bei RealESRGAN)
- `-w/-h`: Zielauflösung (bei libplacebo)
- `--realesrgan-model`: Modell-Name
- `--libplacebo-shader`: Shader-Name
- `-c`: Encoder
- `-e`: Encoder-Optionen (mehrfach verwendbar)

---

## J. Fehlerbehandlung & Edge Cases

### Capture-Fehler
- **Kein Signal:** Status: "Kein Signal von Kamera erkannt"
- **Device nicht gefunden:** Fehlermeldung mit Hinweis auf Geräteauflistung
- **Aufnahme bricht ab:** Automatische Erkennung, Status-Update, Option zum Neustart

### Merge-Fehler
- **Keine Parts gefunden:** Fehlermeldung, Hinweis auf Capture-Phase
- **Concat-Fehler:** Log-Ausgabe, Option zum manuellen Retry

### Upscaling-Fehler
- **Video2X nicht gefunden:** Fehlermeldung mit Pfad-Hinweis
- **GPU nicht verfügbar:** Fallback auf CPU (wenn unterstützt) oder Fehlermeldung
- **Prozess-Abbruch:** Status-Update, Option zum Neustart

### Plex-Export-Fehler
- **Zielordner nicht beschreibbar:** Fehlermeldung, Option zum Pfad-Ändern
- **Datei existiert bereits:** Abfrage: Überschreiben oder neuen Namen wählen
- **Plattenplatz unzureichend:** Fehlermeldung mit benötigtem Platz

---

## K. Logging & Debugging

### Log-Dateien
- Log-Ordner: `dv2plex/logs/`
- Format: `dv2plex_YYYY-MM-DD.log`
- Inhalt:
  - Alle ffmpeg/Video2X-Aufrufe
  - Fehler und Warnungen
  - Status-Änderungen
  - Timestamps

### Debug-Modus
- Optionaler Debug-Modus in Konfiguration
- Erweiterte Log-Ausgabe
- Konsolen-Output für alle Subprozesse

---

## L. Zukünftige Erweiterungen (Optional)

### Automatische Kamera-Steuerung
- Integration von `dvcontrol.exe` oder ähnlichem Tool
- Automatisches Rewind/Play beim Aufnahme-Start

### Batch-Processing
- Mehrere Tapes nacheinander verarbeiten
- Warteschlange für Postprocessing

### Metadaten-Extraktion
- Automatische Erkennung von Aufnahmedatum aus DV-Stream
- Optional: EXIF/Metadata in Output-Datei einbetten

### Qualitätsvorschau
- Schnelle Vorschau des Upscaling-Ergebnisses (nur kurzer Clip)
- Vor dem vollständigen Upscaling testen

### Cloud-Export
- Optional: Direkter Upload zu Cloud-Speicher (z.B. Google Drive, Dropbox)
- Parallel zu oder statt Plex-Export

---

## M. Implementierungs-Hinweise

### Pfad-Auflösung
- **Wichtig:** Alle Pfade relativ zum Programm-Ordner auflösen
- Beispiel: `os.path.join(os.path.dirname(__file__), 'bin', 'ffmpeg.exe')`

### Threading
- Capture-Prozess in separatem Thread
- Preview-Update in separatem Thread
- Upscaling in separatem Thread (blockierend, aber nicht UI)

### Subprozess-Management
- Alle externen Tools (ffmpeg, Video2X) als Subprozesse starten
- Stdout/Stderr für Logging und Fortschritts-Parsing nutzen
- Prozess-Beendigung sauber handhaben

### GUI-Responsiveness
- Lange laufende Operationen nicht im Main-Thread
- Status-Updates über Signals/Slots (PySide6)
- Fortschrittsbalken für Upscaling (falls Video2X Fortschritt ausgibt)

---

**Ende des Lastenhefts**

Dieses Dokument dient als vollständige Spezifikation für die Implementierung der DV2Plex-Anwendung. Alle technischen Details, Abläufe und Strukturen sind hier dokumentiert und können 1:1 als Basis für die Entwicklung verwendet werden.

