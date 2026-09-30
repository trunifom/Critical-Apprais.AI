# SARA - Smart Artificial Review Assistance

SARA ist ein Forschungsprototyp für AI-gestützte Literaturrecherchen. Das Projekt soll Forschende beim Screening von Titel-Abstract-Datensätzen für Scoping Reviews und systematische Reviews unterstützen. Bibliografische Suchergebnisse aus RIS- und BibTeX-Dateien können eingelesen, in DataFrames verarbeitet, zusammengeführt und dedupliziert werden. Ein separates Modul kann Abstracts anhand vorgegebener Review-Ziele sowie Ein- und Ausschlusskriterien an ein Large Language Model (LLM) zur Einschätzung senden.

<img src="/docs/imgs/SARA.png" alt="SARA-Projektgrafik" width="800"/>

> **Projektstatus:** SARA ist derzeit eine Sammlung von Python-Modulen und Forschungs-/Evaluierungsskripten, keine fertige Desktop-, Web- oder Kommandozeilenanwendung. `src/main.py` enthält noch keinen Programmablauf. Die Bibliografie-Funktionen sind mit Unit-Tests versehen; die LLM-Inferenz ist noch nicht durch automatisierte Tests abgesichert. AI-Ausgaben sind Entscheidungshilfen und müssen fachlich geprüft werden.

## Inhalt

- [Funktionen und Ablauf](#funktionen-und-ablauf)
- [Projektstruktur](#projektstruktur)
- [Voraussetzungen und Installation](#voraussetzungen-und-installation)
- [Tests](#tests)
- [Dokumentation](#dokumentation)
- [Datenschutz und API-Schlüssel](#datenschutz-und-api-schlüssel)
- [Bekannte Grenzen](#bekannte-grenzen)

## Funktionen und Ablauf

Der vorgesehene Arbeitsablauf ist:

1. Literaturdatenbanken durchsuchen und Treffer als RIS oder BibTeX exportieren.
2. Jede Exportdatei mit `BibliographicConverter` in bibliografische Einträge bzw. einen Pandas-DataFrame einlesen.
3. Suchläufe als `LiteratureSearchDataset` verwalten und in einem `LiteratureReviewDataset` zusammenführen.
4. Doppelte Einträge anhand ausgewählter Felder wie Titel, Autorenschaft und Jahr finden und entfernen.
5. Abstracts sowie Review-Ziele und Screening-Kriterien an `ModelInference` übergeben.
6. LLM-Antwort, Begründung und Screening-Label als DataFrame auswerten und für eine menschliche Prüfung exportieren.

Die einzelnen Python-Beispiele und die erforderlichen Eingabedaten sind im [User Manual](docs/USER_MANUAL.md) beschrieben. Es gibt gegenwärtig keinen Befehl, der diesen Ablauf vollständig startet.

## Projektstruktur

| Pfad | Zweck |
| --- | --- |
| `src/main.py` | Vorgesehener Programmeinstieg; zurzeit ohne Implementierung. |
| `tools/processing.py` | RIS-/BibTeX-Import und -Export mit `rispy`, `bibtexparser` und Pandas. |
| `tools/literaturdataset.py` | Verwaltung und Zusammenführung von Such- und Review-Datensätzen sowie Duplikatbehandlung. |
| `tools/prompt.py` | Laden einer JSON-Promptdatei und Erzeugung des Abstract-Prompts. |
| `tools/inference.py` | Steuert den LLM-Aufruf je Datensatz und die Umwandlung der Antworten in einen DataFrame; provider-agnostisch. |
| `tools/llm_providers.py` | Provider-Anbindung (OpenAI, SwissGPT/AlpineAI, Anthropic Claude) sowie Modellkatalog für Provider-/Modellauswahl. |
| `prompts/` | Prompttexte und Varianten für das Abstract-Screening. |
| `model_dev/` | DHEM-Beispiel, Kriterien, Evaluierungsnotebook und gespeicherte Forschungsresultate. |
| `tests/unit/` | Unit-Tests für bibliografische Konvertierung und Datensatzlogik. |
| `tests/test_data/` | Kleine RIS-/BibTeX-Beispieldaten für Tests. |
| `tests/output/` | Von den Konvertierungstests geschriebene Beispielausgaben. |
| `docs/` | Projekt- und Nutzungsdokumentation. |

Eine detaillierte Beschreibung der Komponenten und ihrer Beziehungen steht in der [Software-Architektur](docs/SOFTWARE_ARCHITECTURE.md).

## Voraussetzungen und Installation

### Python-Umgebung

Der vorhandene `requirements.txt`-Dateiinhalt ist ein Conda-Export für `osx-arm64` mit Conda-Build-Strings. Er ist nicht als plattformunabhängige `pip`-Requirements-Datei formatiert und sollte unter Windows nicht mit `pip install -r requirements.txt` installiert werden.

Für die Kernfunktionen unter Windows kann eine virtuelle Umgebung mit Python 3.12 verwendet werden:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install pandas rispy bibtexparser openai
```

Falls die PowerShell das Aktivieren blockiert, kann die Ausführungsrichtlinie nur für das aktuelle Terminal angepasst werden:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Die für die Unit-Tests benötigte Testlaufzeit wird zusätzlich installiert:

```powershell
python -m pip install pytest
```

In macOS/Linux entsprechen die Schritte:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install pandas rispy bibtexparser openai pytest
```

Für Modell-Entwicklung und Notebook-Ausführung können weitere Pakete erforderlich sein. Installationsanleitungen für den täglichen Umgang, Terminalbetrieb und Debugging stehen im [Terminal Manual](docs/TERMINAL_GUIDE.md).

`openai` genügt für die Provider `openai` und `swissgpt` (SwissGPT/AlpineAI ist API-kompatibel zu OpenAI). Für den Provider `anthropic` (Claude) wird zusätzlich, nur bei tatsächlicher Nutzung, das optionale Paket `anthropic` benötigt:

```powershell
python -m pip install anthropic
```

### Repository öffnen

Repository klonen und den Projektordner in VS Code öffnen:

```powershell
git clone https://github.zhaw.ch/hirsch-lab/SARA.git
Set-Location .\SARA
code .
```

Wenn das Repository bereits geöffnet ist, genügt ein neues integriertes Terminal in VS Code und die Aktivierung der virtuellen Umgebung.

## Tests

Aus dem Stammverzeichnis des Repositorys:

```powershell
python -m pytest
```

Die Tests lesen RIS- und BibTeX-Beispieldateien und schreiben Konvertierungsergebnisse nach `tests/output/`. Sie prüfen die folgenden Bereiche:

- Einlesen und Umwandeln von RIS-/BibTeX-Dateien.
- Konvertierung von DataFrames zurück zu RIS und BibTeX.
- Duplikaterkennung und -entfernung in einzelnen Suchen.
- Zusammenführen mehrerer Suchdatensätze und anschliessende Duplikatbehandlung.

Ein Fehler bereits beim Import von Pandas deutet eher auf eine beschädigte oder inkompatible Paketumgebung als auf einen Testfehler hin. Insbesondere müssen NumPy und native Abhängigkeiten wie PyArrow zueinander passen. Siehe das [Terminal Manual](docs/TERMINAL_GUIDE.md).

## Dokumentation

- [User Manual](docs/USER_MANUAL.md): Daten importieren, Suchläufe verwalten, Dubletten behandeln, Abstracts screenen und Resultate prüfen.
- [Terminal Manual](docs/TERMINAL_GUIDE.md): virtuelle Umgebung, Befehle in VS Code, Start-/Stoppverhalten und Debugging.
- [Software-Architektur und Quellcode](docs/SOFTWARE_ARCHITECTURE.md): Module, Datenfluss, Schnittstellen, Tests und technische Grenzen.

## Datenschutz und API-Schlüssel

Abstracts können vertrauliche oder personenbezogene Inhalte enthalten. Vor dem Versand an einen externen LLM-Anbieter müssen Datenschutz, institutionelle Richtlinien, Einwilligungen und Vertragsbedingungen geklärt sein. Nur Daten übermitteln, für die eine entsprechende Freigabe besteht.

API-Schlüssel gehören nicht in Quellcode, Prompts, Notebooks, Commits oder Screenshots. `ModelInference` erwartet den Schlüssel als `token`-Argument; der aufrufende Code sollte ihn zur Laufzeit aus einer Umgebungsvariablen oder einem Secret Store lesen. Das Verzeichnis `api/` ist in `.gitignore` ausgeschlossen. Ein ausgeschlossener Pfad schützt jedoch keine bereits committeten Geheimnisse und ersetzt keine Rotation offengelegter Schlüssel.

## Bekannte Grenzen

- Es existiert noch keine fertige CLI, Web-App oder durchgängige Orchestrierung; `src/main.py` ist leer.
- `tools/prompt.py` implementiert Abstract-Prompts, während `fulltext_prompt` noch nicht implementiert ist.
- `prompts/baseline_abstract.json` hat das von `PromptGenerator` erwartete Format. `prompts/prompts_abstract.json` enthält dagegen benannte, verschachtelte Promptvarianten und kann nicht unverändert als Promptdatei an die bestehende Klasse übergeben werden.
- Der DHEM-Beispielcode verwendet einen `prompt_type`-Parameter, den `ModelInference.__init__` nicht annimmt. Das Beispiel ist daher nicht ohne Anpassung ausführbar.
- Die Antwortauswertung erwartet `XXX` oder `YYY` in der letzten Modellzeile. Andere Ausgaben werden momentan als Label `1` gewertet, also nicht als Ausschluss. Resultate sind zu validieren und dürfen nicht ungeprüft als endgültige Screening-Entscheide behandelt werden.
- `model_dev/model_eval.ipynb` enthält gespeicherte Metriken, aber auch eine Anpassung, die Modellvorhersagen bei uneinigen menschlichen Bewertungen durch finale menschliche Entscheide ersetzt. Die angezeigte Accuracy ist daher keine unverzerrte Modellbewertung.
- Für LLM-Inferenz, Promptformate, API-Fehler und End-to-End-Workflows fehlen automatisierte Tests.

# 📚 PRISMA Literature Review System

This project provides an interactive **PRISMA-based** literature review system.  
It allows researchers to **import, screen, and filter scientific studies** following a **structured step-by-step process**.

The system ensures **transparency and reproducibility** by logging each step, enabling researchers to track **how and when** studies were included or excluded.

---

## ✨ **Features**
✔ Import scientific literature from **RIS/BibTeX** files  
✔ Define **research questions, inclusion & exclusion criteria**  
✔ Automatically **detect & remove duplicates**  
✔ Perform **Title/Abstract screening** using an LLM  
✔ Conduct **Full-Text screening** using an LLM  
✔ Export results in **CSV, JSON, RIS, and BibTeX**  
✔ Generate detailed **logs for reproducibility**  

---

## 📌 **Workflow Overview**
The PRISMA workflow is executed in **six key steps**, ensuring a **systematic and transparent** review process.

1️⃣ **Upload Literature Sources**  
   - Import multiple **RIS/BibTeX** files (e.g., PubMed, IEEE Xplore, PsycInfo).  
   
2️⃣ **Define Research Question & Criteria**  
   - Enter the **research question**.  
   - Specify **inclusion & exclusion criteria**.  

3️⃣ **Remove Duplicates**  
   - Identify and remove duplicates **within** and **across** sources.  

4️⃣ **Title & Abstract Screening**  
   - Each study is **screened by an LLM** based on the defined criteria.  
   - Studies are either **included or excluded** with a reasoning log.  

5️⃣ **Full-Text Screening**  
   - The full text is **analyzed by an LLM**, ensuring only relevant studies remain.  

6️⃣ **Export Results**  
   - Final dataset can be exported as **CSV, JSON, RIS, and BibTeX**.  
   - **Intermediate results** (after Title/Abstract screening) are also available.  

---

## 🚀 **Getting Started**

### 🔧 **Installation**
```bash
# Clone the repository
git clone https://github.com/yourusername/prisma-review-system.git

# Navigate into the directory
cd prisma-review-system

# Install dependencies
pip install -r requirements.txt

# Run the Streamlit app
streamlit run app.py




