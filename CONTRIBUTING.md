# Contributing zu DV2Plex

Vielen Dank für dein Interesse, zu DV2Plex beizutragen! 🎉

Dieses Dokument beschreibt, wie du zum Projekt beitragen kannst.

## 📋 Inhaltsverzeichnis

- [Code of Conduct](#code-of-conduct)
- [Wie kann ich beitragen?](#wie-kann-ich-beitragen)
- [Entwicklungsumgebung einrichten](#entwicklungsumgebung-einrichten)
- [Entwicklungsprozess](#entwicklungsprozess)
- [Coding-Standards](#coding-standards)
- [Commit-Messages](#commit-messages)
- [Pull Requests](#pull-requests)

## Code of Conduct

Dieses Projekt folgt einem Code of Conduct. Durch die Teilnahme erwartet man, dass du diesen einhältst.

### Unsere Standards

- Respektvolle und inklusive Sprache verwenden
- Verschiedene Standpunkte und Erfahrungen respektieren
- Konstruktives Feedback geben und annehmen
- Fokus auf das, was am besten für die Community ist

## Wie kann ich beitragen?

### 🐛 Bug Reports

Wenn du einen Bug findest:

1. Prüfe, ob das Issue bereits existiert
2. Erstelle ein neues Issue mit:
   - Klarer, beschreibender Titel
   - Detaillierte Beschreibung des Problems
   - Schritte zur Reproduktion
   - Erwartetes vs. tatsächliches Verhalten
   - System-Informationen (OS, Python-Version, etc.)
   - Screenshots (falls relevant)

### 💡 Feature Requests

Für neue Features:

1. Prüfe, ob das Feature bereits vorgeschlagen wurde
2. Erstelle ein Issue mit:
   - Klare Beschreibung des Features
   - Begründung, warum es nützlich ist
   - Mögliche Implementierungsansätze (optional)

### 📝 Dokumentation

Verbesserungen an der Dokumentation sind immer willkommen:

- Korrektur von Tippfehlern
- Klarere Erklärungen
- Zusätzliche Beispiele
- Übersetzungen

### 🔧 Code-Beiträge

1. Fork das Repository
2. Erstelle einen Feature-Branch
3. Mache deine Änderungen
4. Teste deine Änderungen
5. Sende einen Pull Request

## Entwicklungsumgebung einrichten

### Voraussetzungen

- Python 3.8+
- Git
- (Optional) Virtual Environment

### Setup

```bash
# Repository klonen
git clone https://github.com/yourusername/dv2plex.git
cd dv2plex

# Virtual Environment erstellen
python -m venv venv
source venv/bin/activate  # Linux/Mac
# oder
venv\Scripts\activate  # Windows

# Dependencies installieren
pip install -r requirements.txt

# Entwicklung starten
python -m dv2plex
```

## Entwicklungsprozess

### Branch-Strategie

- `main`: Stabile, produktionsreife Version
- `develop`: Entwicklungs-Branch (falls vorhanden)
- `feature/*`: Neue Features
- `fix/*`: Bugfixes
- `docs/*`: Dokumentations-Änderungen

### Workflow

1. **Issue erstellen** (optional, aber empfohlen)
2. **Branch erstellen**:
   ```bash
   git checkout -b feature/mein-feature
   # oder
   git checkout -b fix/bug-beschreibung
   ```

3. **Änderungen machen**:
   - Code schreiben
   - Tests hinzufügen (falls möglich)
   - Dokumentation aktualisieren

4. **Commits erstellen**:
   ```bash
   git add .
   git commit -m "feat: Beschreibung der Änderung"
   ```

5. **Push und Pull Request**:
   ```bash
   git push origin feature/mein-feature
   ```

## Coding-Standards

### Python

- **PEP 8** befolgen
- **Type Hints** für neue Funktionen
- **Docstrings** im Google-Style:

```python
def example_function(param1: str, param2: int) -> bool:
    """
    Kurze Beschreibung der Funktion.
    
    Args:
        param1: Beschreibung des ersten Parameters
        param2: Beschreibung des zweiten Parameters
    
    Returns:
        Beschreibung des Rückgabewerts
    
    Raises:
        ValueError: Wenn etwas schiefgeht
    """
    pass
```

### Code-Formatierung

- **Maximale Zeilenlänge**: 100 Zeichen (wenn möglich)
- **Imports**: Sortiert und gruppiert (stdlib, third-party, local)
- **Naming**:
  - Funktionen: `snake_case`
  - Klassen: `PascalCase`
  - Konstanten: `UPPER_SNAKE_CASE`

### Beispiel

```python
"""Modul-Dokumentation."""

import os
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtWidgets import QWidget

from dv2plex.config import Config


class ExampleClass:
    """Kurze Klassen-Beschreibung."""
    
    def __init__(self, config: Config):
        """
        Initialisiert die Klasse.
        
        Args:
            config: Konfigurations-Objekt
        """
        self.config = config
    
    def example_method(self, value: int) -> Optional[str]:
        """
        Beispiel-Methode.
        
        Args:
            value: Ein Integer-Wert
        
        Returns:
            Optionaler String-Wert
        """
        if value < 0:
            return None
        return str(value)
```

## Commit-Messages

Wir folgen dem [Conventional Commits](https://www.conventionalcommits.org/) Standard:

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: Neue Features
- `fix`: Bugfixes
- `docs`: Dokumentation
- `style`: Code-Formatierung (keine Logik-Änderungen)
- `refactor`: Code-Refactoring
- `test`: Tests hinzufügen/ändern
- `chore`: Build-Prozess, Dependencies, etc.

### Beispiele

```bash
feat(capture): Add support for multiple capture parts
fix(upscale): Fix memory leak in upscaling engine
docs(readme): Update installation instructions
refactor(config): Simplify configuration loading
```

### Regeln

- **Subject**: Maximal 50 Zeichen, Imperativ ("Add" nicht "Added")
- **Body**: Erkläre das "Was" und "Warum", nicht das "Wie"
- **Footer**: Referenzen zu Issues (z.B. `Closes #123`)

## Pull Requests

### Vor dem Pull Request

- [ ] Code folgt den Coding-Standards
- [ ] Selbst getestet
- [ ] Kommentare und Docstrings hinzugefügt
- [ ] Dokumentation aktualisiert (falls nötig)
- [ ] Keine neuen Warnings
- [ ] Commit-Messages folgen dem Standard

### Pull Request erstellen

1. **Beschreibung**:
   - Was wurde geändert?
   - Warum wurde es geändert?
   - Wie wurde es getestet?

2. **Referenzen**:
   - Verlinke zu relevanten Issues
   - `Closes #123` für automatisches Schließen

3. **Screenshots**:
   - Für UI-Änderungen

4. **Checklist**:
   - Nutze die PR-Template-Checklist

### Review-Prozess

- Maintainer werden den PR reviewen
- Feedback kann gegeben werden
- Änderungen können angefragt werden
- Nach Approval wird der PR gemerged

## Tests

Tests sind aktuell noch in Planung. Wenn du Tests hinzufügst:

- Unit-Tests für einzelne Funktionen
- Integration-Tests für Workflows
- Verwende `pytest` als Test-Framework

## Fragen?

Wenn du Fragen hast:

- Öffne ein Issue mit dem Label "question"
- Diskutiere in GitHub Discussions
- Kontaktiere die Maintainer

## Danke! 🙏

Jeder Beitrag, egal wie klein, ist wertvoll. Danke, dass du DV2Plex besser machst!
