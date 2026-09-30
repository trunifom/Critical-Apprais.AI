# Software-Architektur und Quellcode

## 1. Überblick

SARA ist gegenwärtig eine modulare Python-Codebasis für Teile eines Literaturreview-Workflows. Sie trennt grob zwischen bibliografischer Datenverarbeitung, Dataset-Verwaltung, Prompt-Erzeugung und LLM-Inferenz. Eine Anwendungsschicht, die diese Module als vollständigen Prozess orchestriert, existiert noch nicht.

```text
RIS / BibTeX Exporte
        |
        v
BibliographicConverter  (tools/processing.py)
        |
        v
Pandas DataFrame
        |
        +--> LiteratureSearchDataset  (tools/literaturdataset.py)
        |          |
        |          +--> Duplikate finden / entfernen
        |
        +--> LiteratureReviewDataset
                   |  Suchdatensätze zusammenführen
                   +--> Abstracts extrahieren
                               |
                               v
PromptGenerator  (tools/prompt.py) + Review-Ziele/Kriterien
                               |
                               v
ModelInference  (tools/inference.py) --> OpenAI Chat Completions API
                               |
                               v
Responses --> Resultat-DataFrame --> menschliche Prüfung / Export
```

Der Diagrammablauf beschreibt, wie die vorhandenen Bausteine verbunden werden können. Er ist keine integrierte Pipeline, die sich derzeit über einen Kommandozeilenbefehl starten lässt.

## 2. Laufzeit- und Anwendungsschichten

### 2.1 Einstiegspunkt

`src/main.py` enthält lediglich einen Kommentar. Es gibt dort keine Argumentverarbeitung, Konfiguration, Logging-Einrichtung oder Orchestrierung. `streamlit` ist im Umgebungs-Export enthalten, aber im aktuellen Quellcode gibt es keine Streamlit-Anwendung.

### 2.2 Bibliografischer Adapter: `tools/processing.py`

`BibliographicConverter` kapselt die Ein-/Ausgabe bibliografischer Datensätze:

- Der Konstruktor speichert `file_path` und leitet `file_type` aus dem Suffix ab.
- Für RIS filtert `filter_ris_lines()` erkannte RIS-Tags und `rispy.loads()` parst die Einträge.
- Für BibTeX lädt `bibtexparser` die Einträge.
- `to_dataframe()` gibt die Einträge als Pandas-DataFrame zurück.
- `to_ris()` und `to_bib()` schreiben DataFrame-Zeilen zurück in Exportdateien.
- `ensure_bibtex_fields()` ergänzt für BibTeX-Exporte fehlende Standardwerte und IDs.

Parser- und Dateifehler werden teilweise mit `print()` gemeldet und mit leeren Listen bzw. DataFrames beantwortet. Aufrufender Code muss deshalb einen leeren Rückgabewert prüfen, bevor er mit der Verarbeitung fortfährt. Fehler werden nicht in ein einheitliches projektweites Exception- oder Logging-Modell überführt.

### 2.3 Dataset-Domäne: `tools/literaturdataset.py`

#### `LiteratureSearchDataset`

Repräsentiert die Treffer eines einzelnen Suchlaufs. Gespeichert werden unter anderem:

- ein Label für die Suche bzw. Datenbank,
- der zugrunde liegende DataFrame,
- die ursprüngliche Trefferzahl,
- Zähler für gefundene und entfernte Duplikate,
- die finale Trefferzahl,
- ein lokales, zeitgestempeltes Aktionslog.

`find_duplicates()` markiert alle Zeilen, die mit `keep=False` Duplikate in einem Pandas-Subset sind. Standardmässig sind das `title`, `authors` und `year`. `remove_duplicates()` verwendet `drop_duplicates(..., keep="first")` und aktualisiert den internen DataFrame. Autorenlisten werden dabei in Zeichenketten gewandelt, weil Listen nicht als Vergleichswerte in Pandas-Duplikatoperationen geeignet sind.

#### `LiteratureReviewDataset`

Repräsentiert die Zusammenführung mehrerer Suchläufe. `merge_datasets()` akzeptiert nur Instanzen von `LiteratureSearchDataset`, speichert deren Labels und verbindet nicht-leere DataFrames mit `pandas.concat`. Anschliessend können Duplikate im kombinierten DataFrame gesucht und entfernt werden.

Die Zähler und Logs sind Arbeitsspeicherzustand eines Python-Objekts. Sie werden nicht persistent gespeichert. Mehrmaliges Aufrufen von `merge_datasets()` fügt weitere Suchobjekte zur internen Liste hinzu; ein erneuter Merge arbeitet auf dieser Liste. Aufrufender Code sollte deshalb kontrollieren, ob eine Suche bereits hinzugefügt wurde.

### 2.4 Prompt-Schicht: `tools/prompt.py`

`PromptGenerator` lädt eine JSON-Datei und verwendet für `abstract_prompt()` diese Top-Level-Werte:

- `pre_prompt`: allgemeiner Kontext und Entscheidungsregel,
- `instructions`: Prüfschritte und Ausgabeformat.

Zusammen mit Review-Zielen, Ein- und Ausschlusskriterien und Abstract wird daraus ein englischsprachiger Prompt erzeugt. Die Ziele werden nummeriert und Kriterien als Listen dargestellt.

Die Datei `prompts/baseline_abstract.json` stimmt mit diesem Zugriff überein. `prompts/prompts_abstract.json` enthält dagegen benannte, geschachtelte Promptvarianten. `PromptGenerator` hat keine Auswahl über einen Variantennamen; beim direkten Laden der verschachtelten Datei fehlen die erwarteten Top-Level-Schlüssel, wodurch leere Promptsegmente eingesetzt werden.

`fulltext_prompt()` ist ein Platzhalter und gibt `None` zurück. Fulltext-Screening ist damit nicht implementiert, auch wenn die Inferenzklasse einen `data_type="fulltexts"`-Zweig enthält.

### 2.5 Inferenzschicht: `tools/inference.py` und `tools/llm_providers.py`

`ModelInference` verbindet Dataset, Prompt und einen austauschbaren LLM-Provider. Die eigentliche Provider-Anbindung liegt in `tools/llm_providers.py`, damit sie unabhängig von Prompt-/DataFrame-Logik importierbar ist (z.B. später von einer CLI oder GUI, um Provider und Modelle zur Auswahl anzuzeigen):

- `BaseProvider.complete(system_prompt, user_prompt, model) -> str` ist die gemeinsame Schnittstelle aller Provider. `ModelInference` kennt nur diese Schnittstelle und arbeitet ausschliesslich mit reinem Text, nie mit providerspezifischen Antwortobjekten.
- `OpenAIProvider` kapselt `openai.OpenAI` (Standard-Provider, wie bisher).
- `SwissGPTProvider` erbt von `OpenAIProvider` und setzt nur `base_url="https://api.prod.alpineai.ch/v1"`, da die SwissGPT/AlpineAI-API laut `docs/swissgpt/` vollständig OpenAI-kompatibel ist. Es wird keine zusätzliche Abhängigkeit benötigt. `list_swissgpt_models(api_key)` fragt `GET /v1/models` live ab, da SwissGPT keinen festen, dokumentierten Modellkatalog hat.
- `AnthropicProvider` nutzt die Anthropic Messages API (`system` als eigener Parameter, `max_tokens` erforderlich, Antworttext unter `response.content[0].text`). Das `anthropic`-Paket wird erst beim tatsächlichen Gebrauch (`provider="anthropic"`) lazy importiert; fehlt es, wird ein `ImportError` mit Installationshinweis (`pip install anthropic`) ausgelöst statt eines kryptischen Fehlers.
- `MODEL_REGISTRY` (provider → {model_id: Anzeigename}) sowie `list_providers()`/`list_models(provider)` bilden den auswählbaren Modellkatalog. Er ist rein statisch/deklarativ und noch an keine Oberfläche angebunden – eine künftige GUI/CLI kann ihn direkt importieren, um eine Auswahl anzuzeigen.
- Fehler aller Provider werden auf eine gemeinsame `LLMProviderError` abgebildet, damit `llm_inference()` nicht providerspezifische Exception-Typen kennen muss.

Ablauf in `ModelInference`:

1. Konstruktor erstellt `PromptGenerator`, wählt per `provider`-Parameter (Standard: `"openai"`, rückwärtskompatibel zu bestehenden Aufrufen ohne diesen Parameter) über `get_provider()` die passende Provider-Instanz, und speichert Dataset-Referenz, Datentyp und Modellnamen.
2. `llm_inference()` läuft seriell durch `dataset`.
3. Je Datensatz wird ein Abstract- oder Fulltext-Prompt erzeugt.
4. Pro Datensatz wird `self._provider.complete(...)` aufgerufen.
5. Eine `LLMProviderError` wird ausgegeben und als `None` in der Antwortenliste abgelegt.
6. `response_to_dataframe()` verarbeitet den zurückgegebenen Text. Die letzte Zeile gilt als `decision`; vorangehende Zeilen werden als `reasoning` gespeichert.
7. Das Label ist `0`, falls die Entscheidungszeile `XXX` enthält, sonst `1`.

Eingesetzt wird standardmässig weiterhin OpenAI `gpt-4o`; Temperatur und weitere Sampling-Parameter sind im OpenAI-/SwissGPT-Aufruf fest codiert. Es gibt keine Retry-Strategie, keine Typprüfung des Antwortschemas und keine robuste Validierung der Entscheidung. Ungültige oder leere Entscheidungszeilen können als Label `1` fehlklassifiziert werden. Die Inferenz ist daher als experimenteller Baustein zu behandeln und vor produktiver Verwendung abzusichern.

Der zuvor im System-Prompt fälschlich verwendete Python-Ausdruck `type` (statt des konfigurierten `data_type`) wurde im Rahmen der Provider-Umstellung korrigiert.

### 2.6 Prompt- und Kriterienkonfigurationen

- `prompts/baseline_abstract.json`: flache Prompt-Konfiguration für den bestehenden Prompt-Generator.
- `prompts/prompts_abstract.json`: mehrere verschachtelte Prompt-Varianten, die momentan nicht durch die Laufzeit ausgewählt werden.
- `model_dev/DHEM_criteria.json`: Fallbeispiel mit Forschungszielen sowie Ein- und Ausschlusskriterien zum DHEM-Datensatz.

Prompttext und Kriterien sollten versioniert und im Rahmen eines Review-Protokolls geprüft werden. Änderungen am Prompt können Modellentscheidungen verändern und müssen bei Evaluationen nachvollziehbar dokumentiert werden.

## 3. Forschungs- und Evaluierungscode

### `model_dev/DHEM_abstract.py`

Das Skript zeigt die beabsichtigte Verbindung zu einer DHEM-Excel-Datei: Laden der Kriterien, Extrahieren von Abstracts, Aufruf des Inferenzmoduls, Zusammenführung der Ausgaben mit den manuellen Bewertungen und Schreiben einer Excel-Datei.

Es ist kein portabler Anwendungseinstieg: Es enthält einen lokalen, benutzerspezifischen Datenpfad, lädt ein API-Schlüssel-File aus `api/access.env`, erwartet Dateien ausserhalb des Repositorys und übergibt `prompt_type` an einen Konstruktor, der diesen Parameter nicht unterstützt. Zudem ist `python-dotenv` nicht im vorhandenen Conda-Export aufgeführt. Das Beispiel muss vor Ausführung an die lokale Umgebung und aktuelle API angepasst werden. Geheimnisse und private Forschungsdaten dürfen nicht in Git gelangen.

### `model_dev/model_eval.ipynb`

Das Notebook lädt eine gespeicherte Excel-Ausgabe, bereitet `pred_label` und `true_label` vor und erzeugt Konfusionsmatrizen sowie Klassifikationsberichte mit scikit-learn. Die Datei enthält gespeicherte Zellausgaben, darunter eine Klassifikationsgenauigkeit von 0.81 über 63 Einträge.

Die Auswertung ist methodisch nicht unabhängig: Vor der Metrikberechnung werden für Einträge, bei denen zwei menschliche Rater uneinig waren, die Modellvorhersagen durch die finale menschliche Entscheidung ersetzt. Zudem verwendet die als "non-adjusted" kommentierte Zelle die angepasste Vorhersagevariable. Die dargestellten Zahlen sollten daher nicht als unverzerrte Modellleistung berichtet werden. Für eine belastbare Evaluation müssen Modellvorhersagen unverändert bleiben und anhand unabhängig festgelegter Referenzlabels bewertet werden.

## 4. Datenverträge und Labels

| Bereich | Erwartung / Verhalten |
| --- | --- |
| RIS/BibTeX-Datei | Pfad mit Endung `.ris` oder `.bib`; Parserinhalt muss valides Bibliografiematerial enthalten. |
| Duplikat-Subset | Spalten müssen im DataFrame existieren; Standard für einzelne Suchdatensätze: `title`, `authors`, `year`. |
| Abstract-Dataset | Liste von Texten; Reihenfolge definiert die 1-basierte Ergebnis-ID. |
| Prompt-JSON | Top-Level-Keys `pre_prompt` und `instructions`. |
| LLM-Ausgabe | Letzte Zeile erwartet `XXX` (Ausschluss) oder `YYY` (Einschluss). |
| Ergebnislabel | `0` wenn `XXX` in der letzten Zeile vorkommt, sonst `1`; ungültige Werte werden aktuell nicht abgewiesen. |

## 5. Tests und Abdeckung

Die Unit-Tests befinden sich in `tests/unit/`:

- `test_bibliographic_converter.py` prüft Dateityp-Erkennung, RIS-/BibTeX-Lesen, RIS-Zeilenfilter, DataFrame-Import sowie beide Exportformate.
- `test_literaturesearchdataset.py` prüft Initialisierung, Duplikatzählung, Deduplizierung, Zusammenführung und Labels.
- `test_inference.py` prüft die Provider-Umschaltung in `tools/llm_providers.py`/`tools/inference.py` (Standard-Provider OpenAI, SwissGPT-Base-URL, Anthropic-Systemprompt-Parameter, fehlendes `anthropic`-Paket, unbekannter Provider, Antwort-Parsing) mit gemockten Clients, ohne echte API-Schlüssel oder Netzwerkzugriff.

Die Testdaten liegen in `tests/test_data/`; erzeugte Exportbeispiele in `tests/output/`. Insbesondere gibt es weiterhin keine Tests für Prompt-/DHEM-Integration, Kostenkontrolle oder den Ende-zu-Ende-Workflow.

Ausführung:

```powershell
python -m pytest
```

Ein fehlschlagender Testimport aufgrund inkompatibler NumPy-/PyArrow-Binärpakete ist zunächst ein Umgebungsfehler. Installation und Debugging sind im [Terminal Manual](TERMINAL_GUIDE.md) beschrieben.

## 6. Abhängigkeiten und Konfiguration

Der Repository-`requirements.txt` ist ein Conda-Export (`osx-arm64`) mit konkreten Conda-/Pip-Build-Einträgen. Er umfasst unter anderem Pandas, RISpy, BibTeXParser, OpenAI, NumPy, scikit-learn, Jupyter und Streamlit. Nicht alle aufgeführten Bibliotheken werden von der Kernfunktion verwendet; der Export ist weder eine gepflegte minimale Dependency-Liste noch eine Windows-lockdatei.

Im Quellcode wird kein automatisches Laden einer allgemeinen `.env` für die Kerninferenz durchgeführt. `ModelInference` nimmt den API-Schlüssel als Konstruktorargument (`token`), passend zum gewählten `provider`. Ein Aufrufer sollte den Wert zur Laufzeit sicher beziehen und die an den externen Anbieter gesendeten Daten zuvor datenschutzrechtlich freigeben.

Das `anthropic`-Paket ist eine optionale Abhängigkeit: Es wird nur benötigt und erst zur Laufzeit importiert, wenn `provider="anthropic"` tatsächlich verwendet wird. Für `provider="openai"` und `provider="swissgpt"` genügt weiterhin das `openai`-Paket, da SwissGPT/AlpineAI dessen API-Format übernimmt.

## 7. Aktuelle Architekturgrenzen und nächste technische Schritte

Die vorhandene Basis ermöglicht bibliografische Datenverarbeitung und einen experimentellen Abstract-LLM-Aufruf. Für eine robuste, nutzergeführte Anwendung wären unter anderem folgende Ergänzungen erforderlich:

- Ein klar definierter Einstiegspunkt und Orchestrierung für Import, Bereinigung, Screening und Export.
- Eine validierte Konfiguration, die Promptvarianten explizit auswählt und Schemafehler früh meldet.
- Einheitliche Exceptions und strukturiertes Logging statt gemischter `print()`-Meldungen.
- Schema-/Typvalidierung der LLM-Antwort mit explizitem Status für Unsicherheit und ungültige Ausgabe.
- Kontrollierte Wiederholungen, Rate-Limit-Behandlung, Fortschritt und persistente Zwischenergebnisse.
- Unit- und Integrationstests mit gemockter API statt echtem Netzaufruf.
- Ein nachvollziehbares, unabhängiges Evaluationsdesign ohne Überschreiben der Modellvorhersagen.
- Eine portable, getestete Paketdefinition für unterstützte Python-Versionen und Betriebssysteme.
- Explizite Datenschutz-, Aufbewahrungs- und Exportregeln für Forschungsdaten.
