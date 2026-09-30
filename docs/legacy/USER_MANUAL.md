# SARA User Manual

## 1. Zweck und Geltungsbereich

SARA ist ein Python-Forschungsprototyp für die Unterstützung des Titel-Abstract-Screenings in systematischen und Scoping Reviews. Dieses Manual beschreibt die vorhandenen Bibliotheksfunktionen und zeigt, wie sie in einem eigenen Python-Skript kombiniert werden können.

SARA besitzt aktuell weder eine fertige Benutzeroberfläche noch einen CLI-Befehl, der den vollständigen Workflow ausführt. Die Nutzung erfolgt durch Import der Python-Klassen. AI-Ergebnisse sind Vorschläge für die menschliche Prüfung und keine autonome finale Studienauswahl.

## 2. Voraussetzungen

- Python 3.12 wird durch den vorhandenen Umgebungs-Export nahegelegt.
- Für RIS/BibTeX und DataFrames werden `pandas`, `rispy` und `bibtexparser` benötigt.
- Für das LLM-Modul wird zusätzlich das OpenAI-Python-Paket benötigt.
- Die Einrichtung der Umgebung ist im [Terminal Manual](TERMINAL_GUIDE.md) erläutert.
- Für die Nutzung von LLM-Inferenz braucht der aufrufende Prozess einen gültigen API-Schlüssel und Netzwerkzugriff.

Der Repository-`requirements.txt` ist ein Conda-Export für `osx-arm64`, kein allgemeines `pip`-Manifest. Insbesondere unter Windows die Installationsschritte im [README](../README.md) verwenden.

## 3. Grundlegender Screening-Ablauf

### 3.1 Datenbankexport vorbereiten

1. Suche in den gewünschten Literaturdatenbanken durchführen.
2. Jede Suche separat exportieren, vorzugsweise in RIS oder BibTeX.
3. Exportdateien in einen Arbeitsordner legen. Die Rohdaten sollten unverändert als nachvollziehbare Quelle erhalten bleiben.
4. Prüfen, ob die Dateien Abstracts, Titel, Autorenschaft und Jahr enthalten. Die RIS-/BibTeX-Parser können nur Felder übernehmen, die in den Quelldateien vorhanden sind.

Es gibt keine automatische Verbindung zu Literaturdatenbanken. SARA führt die Suche nicht selbst aus.

### 3.2 Datei importieren

`BibliographicConverter` bestimmt den Dateityp anhand der Dateiendung (`.ris` oder `.bib`) und wandelt den Inhalt mit `to_dataframe()` in einen Pandas-DataFrame um:

```python
from tools.processing import BibliographicConverter

converter = BibliographicConverter("data/search_database_a.ris")
records = converter.to_dataframe()
print(records.shape)
print(records.columns.tolist())
```

Die tatsächlichen Feldnamen hängen vom Exportformat und Parser ab. Vor der Duplikatbehandlung und Inferenz die Spalten mit `records.columns` prüfen. Unterstützt werden `.ris` und `.bib`; andere Endungen werden nicht verarbeitet. Ein nicht lesbares oder nicht unterstütztes Format kann zu einem leeren DataFrame führen.

### 3.3 Mehrere Suchen verwalten und zusammenführen

Eine einzelne Suche kann als `LiteratureSearchDataset` mit einem aussagekräftigen Label verwaltet werden:

```python
from tools.literaturdataset import LiteratureSearchDataset

search_a = LiteratureSearchDataset("database_a_2026-09-29", records)
print(search_a.get_original_count())
```

Für jede Suchdatei einen eigenen Converter und Dataset-Wrapper anlegen. Anschliessend können die Suchläufe in einem Review-Datensatz zusammengeführt werden:

```python
from tools.literaturdataset import LiteratureReviewDataset

review = LiteratureReviewDataset(
    label="review_screening",
    datasets=[search_a, search_b],
)
combined = review.get_dataframe()
print(review.get_merged_labels())
print(review.get_original_count())
```

Der Review-Datensatz speichert die übergebenen Suchobjekte und kombiniert deren DataFrames. Wenn dieselben Objekte bereits vorher verändert wurden, etwa durch Duplikatentfernung, beziehen sich die zusammengeführten DataFrames auf deren aktuellen Zustand; `get_original_count()` summiert jedoch die ursprünglich erfassten Trefferzahlen der Suchobjekte.

### 3.4 Dubletten finden und entfernen

Die Such-Dataset-Klasse verwendet standardmässig `title`, `authors` und `year`. Alle angegebenen Spalten müssen vorhanden sein. Ein explizites `subset` macht die Vergleichsregel sichtbar:

```python
duplicate_rows = search_a.find_duplicates(
    subset=["title", "authors", "year"]
)
print(search_a.get_duplicates_found())

search_a.remove_duplicates(subset=["title", "authors", "year"])
clean_records = search_a.get_dataframe()
print(search_a.get_duplicates_removed())
print(search_a.get_final_count())
```

Für einen kombinierten Datensatz:

```python
review.find_duplicates(subset=["title", "authors", "year"])
review.remove_duplicates(subset=["title", "authors", "year"])
```

Die Erkennung ist ein exakter Vergleich der DataFrame-Werte, keine unscharfe oder DOI-basierte Ähnlichkeitssuche. Listen in der Spalte `authors` werden in Zeichenketten umgewandelt, damit Pandas sie vergleichen kann. Diese Umwandlung verändert den DataFrame. Vor dem Entfernen die gefundenen Zeilen fachlich kontrollieren und die Originalexporte aufbewahren.

Jedes Dataset stellt ausserdem ein einfaches Aktionsprotokoll bereit:

```python
print(search_a.get_log())
print(review.get_log())
```

Die Logs enthalten Erstellungs-, Merge- und Duplikataktionen mit lokalen Zeitstempeln. Sie sind keine persistente Audit-Datenbank.

### 3.5 Abstracts und Kriterien vorbereiten

Das Inferenzmodul erwartet eine Python-Liste von Abstract-Texten. Fehlende Werte vor dem Aufruf entfernen und die Zuordnung zur Ausgangsdatei dokumentieren:

```python
screening_records = clean_records.dropna(subset=["abstract"]).copy()
abstracts = screening_records["abstract"].astype(str).tolist()
```

Die Spalte muss im eingelesenen DataFrame tatsächlich `abstract` heissen. Falls ein Datenbankexport einen anderen Feldnamen erzeugt, diesen vor dem Aufruf explizit in `abstract` umbenennen.

Review-Ziele, Ein- und Ausschlusskriterien sind Listen von Texten, zum Beispiel:

```python
objectives = ["Review objective goes here"]
inclusion_criteria = ["Criterion that must be met"]
exclusion_criteria = ["Criterion that excludes the study"]
```

Kriterien sollten präzise, voneinander unterscheidbar und fachlich mit dem Review-Protokoll abgestimmt sein. Kriterienkonfigurationen in `model_dev/` sind Beispieldaten für einen bestimmten Forschungsfall und nicht als universelle Kriterien zu verstehen.

### 3.6 Promptdatei wählen

`PromptGenerator` erwartet eine JSON-Datei mit zwei Top-Level-Schlüsseln:

```json
{
  "pre_prompt": "Context and decision rule",
  "instructions": "Output instructions, including the expected final label"
}
```

Die Datei `prompts/baseline_abstract.json` entspricht diesem Format. `prompts/prompts_abstract.json` enthält benannte Varianten unter `baseline_abstract` und `less_restrictive_abstract`; die bestehende Klasse wählt daraus keine Variante aus. Diese verschachtelte Datei daher nicht unverändert als `prompts_path` verwenden.

Die aktuellen Prompts verlangen die letzte Antwortzeile `XXX` für Ausschluss oder `YYY` für Einschluss. Die Variante `baseline_abstract.json` enthält sowohl Ein- als auch Ausschlusskriterien; die weniger restriktive Variante liegt verschachtelt in `prompts_abstract.json`.

### 3.7 LLM-Inferenz ausführen

`ModelInference` nimmt den Promptpfad, die Liste der Abstracts und den API-Schlüssel als Argumente entgegen. Der Schlüssel wird hier aus einer Umgebungsvariablen gelesen und weder in den Quellcode geschrieben noch im Terminal ausgegeben:

```python
import os
from tools.inference import ModelInference

api_token = os.environ["OPENAI_API_KEY"]
inference = ModelInference(
    prompts_path="prompts/baseline_abstract.json",
    dataset=abstracts,
    token=api_token,
    data_type="abstracts",
    model="gpt-4o-mini",
)
responses = inference.llm_inference(
    objectives=objectives,
    inclusion_criteria=inclusion_criteria,
    exclusion_criteria=exclusion_criteria,
)
results = inference.response_to_dataframe(responses)
```

Der Aufruf erfolgt gegenwärtig seriell, Abstract für Abstract. Es gibt in dieser Implementierung keine sichtbare Batchverarbeitung, Fortschrittsanzeige, automatische Wiederholung oder Speicherung nach jedem Datensatz. Der Aufruf kann daher bei grossen Datenmengen lange dauern und Kosten verursachen.

#### Provider und Modell wählen

`ModelInference` unterstützt neben OpenAI auch SwissGPT/AlpineAI (OpenAI-kompatibel, eigener `base_url`) und Anthropic Claude (separates `anthropic`-Paket, nur bei Bedarf installieren: `pip install anthropic`). Der Provider wird über den zusätzlichen Parameter `provider` gewählt (Standard: `"openai"`, damit bestehender Code ohne diesen Parameter unverändert funktioniert); `token` ist dabei immer der zum gewählten Provider passende API-Schlüssel:

```python
inference = ModelInference(
    prompts_path="prompts/baseline_abstract.json",
    dataset=abstracts,
    token=os.environ["ANTHROPIC_API_KEY"],
    data_type="abstracts",
    model="claude-sonnet-5",
    provider="anthropic",
)
```

Welche Provider und Modelle zur Auswahl stehen, lässt sich programmatisch abfragen, statt Namen fest im Code zu verdrahten — nützlich für eine spätere Auswahl per Kommandozeile oder GUI:

```python
from tools.llm_providers import list_providers, list_models

list_providers()        # ["openai", "swissgpt", "anthropic"]
list_models("anthropic")  # {"claude-sonnet-5": "Claude Sonnet 5", ...}
```

SwissGPT hat keinen festen Modellkatalog; `tools.llm_providers.list_swissgpt_models(api_key)` fragt die verfügbaren Modelle live über die AlpineAI-API ab.

In PowerShell kann die Umgebungsvariable für das aktuelle Terminal gesetzt werden:

```powershell
$env:OPENAI_API_KEY = "WERT HIER DIREKT IM TERMINAL EINGEBEN"
```

Der Beispieltext ist durch den tatsächlichen Schlüssel zu ersetzen, aber niemals als Code oder Commit zu speichern. Der Inferenzkonstruktor erhält den Wert als `token`; die Umgebungsvariable wird nicht automatisch von `ModelInference` gelesen. Beim Schliessen des Terminals wird eine nur für dieses Terminal gesetzte Variable verworfen.

### 3.8 Resultate verstehen und exportieren

`response_to_dataframe()` erstellt normalerweise diese Spalten:

| Spalte | Bedeutung |
| --- | --- |
| `id` | 1-basierter Index des Eintrags in der übergebenen Abstract-Liste. |
| `abstracts` | Der verarbeitete Abstract-Text, wenn `data_type="abstracts"`. |
| `reasoning` | Antworttext vor der letzten Zeile. |
| `decision` | Letzte Antwortzeile, vorgesehen als `XXX` oder `YYY`. |
| `label` | `0`, falls die Decision den Text `XXX` enthält; andernfalls `1`. |

Das Resultat kann für die menschliche Prüfung gespeichert werden:

```python
results.to_csv("screening_results.csv", index=False)
```

Die Zuordnung zurück zu den bibliografischen Einträgen muss anhand der ursprünglichen Reihenfolge bzw. der `id` sorgfältig hergestellt werden. Bei fehlgeschlagenen API-Verbindungen werden `None`-Antworten aus dem Resultat ausgelassen. Daher nicht davon ausgehen, dass die Zeilenposition im Resultat immer der ursprünglichen Position entspricht; die `id` ist dafür vorgesehen.

Das aktuelle Labeling behandelt jede nicht-leere Decision ohne `XXX` als `1`, auch unerwartete oder ungültige Ausgaben. Vor einer Auswertung `decision` kontrollieren und unerwartete Antworten als Fehler bzw. manuelle Prüfung behandeln. Im Prompt steht `YYY` für Einschluss; die Software setzt jedoch für jede Antwort ohne `XXX` das Label `1`.

## 4. RIS- und BibTeX-Dateien exportieren

Ein DataFrame kann zurück in BibTeX oder RIS geschrieben werden:

```python
converter.to_bib(clean_records, "output/cleaned_records.bib")
converter.to_ris(clean_records, "output/cleaned_records.ris")
```

Für BibTeX ergänzt der Converter fehlende Standardfelder und eine generierte ID. Das ist eine technische Ergänzung und garantiert nicht, dass die vervollständigten Metadaten korrekt sind. Exportdateien nach dem Schreiben stichprobenartig öffnen und gegen die Quelldaten prüfen.

## 5. Fehlerbehandlung und praktische Hinweise

- **Leerer DataFrame:** Dateipfad, Dateiendung, Kodierung und Dateiinhalt prüfen. Parserfehler werden teilweise als Meldung auf der Konsole ausgegeben.
- **Fehlende Spalten beim Deduplizieren:** Erst `records.columns` prüfen; Titel, Autorenschaft und Jahr müssen im verwendeten `subset` existieren.
- **Fehlender Abstract:** Vor Inferenz fehlende Abstracts entfernen oder die betreffenden Einträge getrennt manuell prüfen.
- **OpenAI-Verbindungsfehler:** Der Code fängt `APIConnectionError` ab und trägt `None` ein. Andere API-Fehler, etwa Authentifizierungs- oder Kontingentfehler, können als Exception abbrechen.
- **Antwort ohne erwartetes Label:** Nicht als verlässliche Einschlussentscheidung werten. Die aktuelle Umwandlung setzt sonst Label `1`.
- **API-Kosten und sensible Daten:** Vor dem Lauf Anzahl und Inhalt der Abstracts prüfen, mögliche Kosten kalkulieren und nur zur Übermittlung freigegebene Daten verwenden.
- **Fulltext:** `data_type="fulltexts"` ist vorgesehen, aber `fulltext_prompt()` ist nicht implementiert. Fulltext-Screening ist deshalb nicht einsatzbereit.

## 6. Verantwortungsvolle Nutzung

Ein LLM kann relevante Studien übersehen, ungeeignete Studien aufnehmen, Kriterien missverstehen oder plausible, aber falsche Begründungen erzeugen. Fachpersonen müssen die Resultate kontrollieren, Unsicherheiten dokumentieren und den Screening-Prozess entsprechend dem Review-Protokoll durchführen. Für belastbare Modellvergleiche sind ein vorab festgelegtes Evaluationsdesign, unveränderte Gold-Labels und unabhängige Testdaten erforderlich.
