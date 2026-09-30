# Terminal Manual: Starten, Stoppen und Debuggen

## 1. Was bedeutet "Starten" bei SARA?

Der aktuelle Repository-Stand enthält noch keine dauerhaft laufende Anwendung und keinen implementierten CLI- oder Web-App-Einstiegspunkt. `src/main.py` ist leer. Es gibt deshalb keinen SARA-Server, der mit `streamlit run ...` oder `python src/main.py` gestartet und später gestoppt werden könnte.

Die vorhandenen Funktionen werden in Python-Skripten aufgerufen. Ein Testlauf ist ein endlicher Prozess; ein Notebook läuft in einem Jupyter-Kernel. Dieses Manual beschreibt diese tatsächlich vorhandenen Betriebsarten und kennzeichnet nicht implementierte Funktionen als solche.

## 2. VS-Code-Terminal öffnen

1. Repository-Stammverzeichnis in VS Code öffnen. Das Stammverzeichnis enthält `README.md`, `requirements.txt`, `src/`, `tools/` und `tests/`.
2. Menü **Terminal > New Terminal** wählen. VS Code öffnet unter Windows standardmässig PowerShell.
3. Kontrollieren, dass das Terminal im Repository-Stammverzeichnis steht:

```powershell
Get-Location
Get-ChildItem
```

Falls nötig in das Repository wechseln:

```powershell
Set-Location "C:\Users\<Benutzer>\Documents\GitHub\SARA"
```

## 3. Python-Umgebung

### 3.1 Virtuelle Umgebung für die Kernmodule erstellen

In PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install pandas rispy bibtexparser openai pytest
```

Bei einer PowerShell-Sperre für lokale Aktivierungsskripte kann die Richtlinie im aktuellen Prozess gelockert werden; diese Einstellung bleibt auf das Terminal beschränkt:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Die Eingabeaufforderung zeigt üblicherweise `(.venv)` am Anfang, wenn die Umgebung aktiv ist. Python und Pip prüfen:

```powershell
python --version
python -m pip --version
python -c "import pandas, rispy, bibtexparser, openai; print('Kernpakete verfügbar')"
```

In macOS/Linux wird die Umgebung so aktiviert:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install pandas rispy bibtexparser openai pytest
```

Der eingecheckte `requirements.txt` ist ein plattformspezifischer Conda-Export für `osx-arm64`, keine portable Pip-Liste. Die enthaltenen Conda-Build-Strings können nicht zuverlässig mit `pip install -r requirements.txt` installiert werden. Für optionale Notebooks und Model-Development können weitere Pakete notwendig sein.

### 3.2 VS Code Interpreter auswählen

1. `Ctrl+Shift+P` öffnen.
2. **Python: Select Interpreter** suchen.
3. Den Interpreter im Projektordner `.venv` auswählen.
4. Ein neues Terminal öffnen, damit VS Code die gewählte Umgebung aktiviert.

Terminal-Python und VS-Code-Python sollten auf dieselbe virtuelle Umgebung zeigen:

```powershell
python -c "import sys; print(sys.executable)"
```

## 4. Vorhandene Prozesse ausführen

### Unit-Tests

Vom Projektstamm aus:

```powershell
python -m pytest
```

Für einen einzelnen Testbereich:

```powershell
python -m pytest tests/unit/test_bibliographic_converter.py -v
python -m pytest tests/unit/test_literaturesearchdataset.py -v
```

`pytest` beendet sich nach dem Lauf selbst. Es wird kein Server gestartet. Die Converter-Tests schreiben Ausgaben nach `tests/output/`; prüfe Änderungen dort mit `git status`.

### Bibliografie- oder Inferenzskript

Es gibt noch kein vollständiges Skript im `src/`-Ordner. Ein eigenes, vom Repository-Stamm gestartetes Skript kann die Module importieren:

```powershell
python .\mein_workflow.py
```

Relative Pfade wie `prompts/baseline_abstract.json` werden relativ zum aktuellen Arbeitsverzeichnis ausgewertet. Daher vor dem Start in den Repository-Stamm wechseln.

### Notebook

Das Evaluierungsnotebook liegt unter `model_dev/model_eval.ipynb`. Notebook-Kernel über VS Code starten und Zellen schrittweise ausführen. Das Notebook erwartet bestehende Evaluierungsdateien und relative Pfade; es ist keine allgemeine Screening-Oberfläche. Die gespeicherten Auswertungen sind zudem nicht als unverzerrte Modellmessung zu interpretieren; siehe [Architekturbeschreibung](SOFTWARE_ARCHITECTURE.md).

### API-Schlüssel im Terminal

`ModelInference` erhält den API-Schlüssel als `token`-Argument. Das Terminal kann ihn für die aktuelle PowerShell-Sitzung bereitstellen:

```powershell
$env:OPENAI_API_KEY = "WERT HIER DIREKT IM TERMINAL EINGEBEN"
```

Aufrufercode liest ihn zum Beispiel mit `os.environ["OPENAI_API_KEY"]` und übergibt den Wert an den Konstruktor. Den Schlüssel nicht in Skripte, Notebooks, Prompts, Kommandozeilenargumente oder Git eintragen. Das Geheimnis nicht ausgeben lassen. Nach dem Schliessen des Terminals wird die sitzungsbezogene Variable entfernt.

## 5. Prozesse stoppen und Umgebung verlassen

- **Unit-Test oder endliches Python-Skript:** Der Prozess endet automatisch, wenn die Ausführung fertig ist.
- **Laufendes Skript oder Testlauf abbrechen:** Im betreffenden Terminal `Ctrl+C` drücken. Ein abgebrochener Inferenzlauf kann bereits angefallene API-Kosten verursachen und gespeicherte Zwischenergebnisse gehen verloren, sofern das Skript sie nicht selbst gespeichert hat.
- **Python-REPL beenden:** `exit()` eingeben oder `Ctrl+Z`, danach `Enter` drücken.
- **Jupyter-Kernel:** Notebook-Menü **Restart** oder **Shut Down** verwenden. Ein Kernel-Neustart verwirft Variablen im Arbeitsspeicher.
- **Virtuelle Umgebung verlassen:** `deactivate` eingeben.
- **VS-Code-Terminal schliessen:** Papierkorb-Symbol im Terminal-Panel oder `exit` verwenden.

Es gibt keinen SARA-Dienst, der nach diesen Schritten im Hintergrund weiterlaufen sollte.

## 6. Debugging

### 6.1 Fehler eingrenzen

1. Vollständige Fehlermeldung und Traceback sichern.
2. Arbeitsverzeichnis und Interpreter prüfen (`Get-Location`, `python -c "import sys; print(sys.executable)"`).
3. Import bzw. Installation des betroffenen Pakets prüfen.
4. Erst den kleinstmöglichen Test ausführen, dann den vollständigen Testsatz.
5. Bei Importfehlern Paketversionen auf ABI-Konflikte prüfen; bei SARA-Fehlern Eingabedatei, DataFrame-Spalten und Promptformat kontrollieren.

Paketversionen anzeigen:

```powershell
python -m pip show numpy pandas pyarrow rispy bibtexparser openai
python -m pip check
```

### 6.2 VS-Code-Debugger

1. Betroffene Python-Datei öffnen.
2. Links neben einer Codezeile klicken, um einen Breakpoint zu setzen.
3. **Run and Debug** öffnen und die Python-Datei oder den vorgesehenen Test konfigurieren.
4. Aufruf mit genau denselben Eingabedateien und derselben virtuellen Umgebung wie im Terminal starten.
5. Variablen, Call Stack und Exception im Debug-Panel prüfen.

Zum Debuggen der vorhandenen `unittest`-Dateien können diese direkt ausgeführt werden, da sie einen `unittest.main()`-Einstieg haben:

```powershell
python -m pdb .\tests\unit\test_bibliographic_converter.py
```

Im `pdb`-Prompt sind die häufigsten Befehle `n` (nächste Zeile), `s` (in Funktion springen), `c` (bis zum nächsten Breakpoint fortsetzen), `p variable` (Wert ausgeben) und `q` (Debugger beenden). Für Pytest kann in VS Code eine Debug-Konfiguration mit `module: pytest` und dem Testpfad als Argument angelegt werden.

### 6.3 Häufige Fehler

**`ModuleNotFoundError` für ein Kernpaket**

Wahrscheinlich wurde das falsche Python verwendet oder das Paket fehlt in der aktiven Umgebung. Interpreterpfad prüfen und Pakete mit genau diesem Interpreter installieren:

```powershell
python -m pip install pandas rispy bibtexparser openai pytest
```

**Pandas-/PyArrow-Fehler mit NumPy-ABI-Hinweis**

Ein nativer Build von PyArrow oder einer anderen Erweiterung wurde gegen NumPy 1.x erstellt, aber die aktive Umgebung lädt NumPy 2.x. Nicht wahllos Pakete in der globalen Conda-Installation ändern. In einer frischen `.venv` die Kernabhängigkeiten installieren oder die beteiligten Pakete in einer konsistenten Umgebung neu installieren. Versionen mit `python -m pip show numpy pyarrow pandas` dokumentieren.

**`KeyError` bei `find_duplicates` oder `remove_duplicates`**

Der DataFrame enthält nicht alle im `subset` genannten Spalten. `print(df.columns.tolist())` ausführen und tatsächliche Feldnamen verwenden oder vor dem Aufruf normalisieren. Die Standardspalten sind `title`, `authors` und `year`.

**Kein Abstract-Feld bzw. leere Inferenzliste**

Datenbankexport und Parser-Spalten prüfen. Fehlende Abstracts herausfiltern und einen leeren Datensatz nicht an die Inferenz übergeben.

**Prompt scheint leer oder Auswahl der Variante greift nicht**

`PromptGenerator` erwartet `pre_prompt` und `instructions` direkt auf oberster JSON-Ebene. `prompts/prompts_abstract.json` verschachtelt diese unter Namen wie `baseline_abstract`; diese Variantenwahl implementiert der aktuelle Code nicht.

**DHEM-Skript meldet unerwartetes Argument `prompt_type`**

`model_dev/DHEM_abstract.py` ruft `ModelInference` mit `prompt_type` auf, aber der aktuelle Konstruktor kennt dieses Argument nicht. Das Forschungsbeispiel ist in seinem jetzigen Zustand nicht direkt lauffähig.

**OpenAI-Fehler**

API-Schlüssel, Berechtigung, Modellname, Netzwerk und Kontingent prüfen. Im aktuellen Inferenzcode wird nur `APIConnectionError` abgefangen; andere API-Ausnahmen können den Lauf beenden. Schlüssel niemals zur Fehlersuche im Log ausgeben.

## 7. Ergebnis und Arbeitsbaum kontrollieren

Nach Tests oder Skripten:

```powershell
git status --short
```

Vor einem Commit prüfen, ob erzeugte Dateien, lokale Rohdaten oder Geheimnisse auftauchen. Testausgaben in `tests/output/` sind reproduzierbare Artefakte; nur bei einer gezielten Änderung committen. API-Schlüssel und sensible Datensätze nie committen.
