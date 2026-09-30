# ENTWICKLERDOKUMENTATION.md - Critical Apprais.AI (Software-Dokumentation)

Stand: 2026-09-30, Version 0.0.1. Zielgruppe: Entwickler:innen und KI-Agenten, die am Code arbeiten.
Aufbau und Begründungen: `docs/ARCHITEKTUR.md`. Bedienung: `docs/BENUTZERHANDBUCH.md`. Regeln für Agenten: `AGENTS.md`.
Was **umgesetzt** ist, steht hier; Geplantes ist mit *(geplant)* gekennzeichnet.

## 1. Entwicklungsumgebung

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,import,cli]"
python -m pytest -q            # alle Tests, ca. 1 Minute (Anzahl: Umsetzungsplan)
python -m ruff check .         # Lint (schliesst reference/ aus)
python -m mypy src             # Typen
```

| Extra | Inhalt | Wofür |
|---|---|---|
| (Kern) | pandas, pydantic, pyyaml | immer |
| `dev` | pytest, pytest-asyncio, hypothesis, respx, ruff, mypy | Entwicklung |
| `import` | rispy, pybtex, openpyxl, pymupdf, pdfplumber, pylatexenc | Import; **benötigt** werden heute `openpyxl` (XLSX) und `pylatexenc` (BibTeX) |
| `cli` | typer, rich | Befehl `crapai` |
| `llm-openai`, `llm-anthropic`, `ui`, `stats` | *(geplant)* | spätere Meilensteine |

Neue Abhängigkeiten ausserhalb dieser Extras nur nach Rückfrage. CI: `.github/workflows/ci.yml` (Ruff, mypy, pytest auf Windows/Linux/macOS, Python 3.11-3.13, ohne `live`-Tests).

## 1a. Lizenz

Der Code steht unter der **PolyForm Noncommercial 1.0.0** (`LICENSE`, ADR 0016): nicht kommerziell frei nutzbar, kommerziell ausgeschlossen. Der Lizenztext darf nicht verändert werden
(`tests/unit/test_license.py` prüft den Hash). Beiträge stehen unter derselben Lizenz. Fremdmaterial im Repository ist nicht von ihr erfasst. Neue Abhängigkeiten müssen mit dieser Lizenz
verträglich sein; im Zweifel nachfragen.

## 2. Verzeichnisse

| Pfad | Inhalt |
|---|---|
| `src/crapai/` | der Code (Paket `crapai`, ADR 0017) |
| `tests/unit`, `tests/integration` | Tests |
| `tests/data/` | öffentliche Beispielexporte + `EXPECTED.json` (Sollzahlen), **nicht ändern** |
| `tests/data_large/` | grosse Dateien, nicht versioniert (Marker `large`) |
| `tests/legacy_runs/`, `tests/expected/` | archivierte Läufe/Berichte des Vorgängers, **nicht ändern** |
| `reference/` | Vorgängercode, **nur lesen, nie importieren** |
| `templates/` | Beispielkonfiguration, Modelle, Preise, Prompts (Daten) |
| `docs/` | Dokumente (Deutsch); `docs/adr/` Entscheide |
| `tasks/` | Aufgabenkarten; Stand in `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md` |

## 3. Öffentliche Schnittstellen (Referenz)

Alle Funktionen sind typisiert und haben Docstrings (Englisch). Hier die wichtigsten Einstiege.

### 3.1 Fehler (`crapai.errors`)

```python
class SaraError(Exception):            # code, user_message, hint, details, text_key
ConfigError (E203) · ImportFailed (E101) · ParseError (E304) · StorageError (E401)
ProviderError (E305) → AuthError (E301), RateLimited (E302), TransientError (E305),
                       ContextTooLong (E303), ContentRefused (E306), QuotaExceeded (E307)
EvaluationError (E501)
```
Jede Auslösestelle darf den Code überschreiben (`ConfigError(..., code="E201")`). `details` enthält nie Geheimnisse oder Abstracts.

### 3.2 Konfiguration (`crapai.config`)

```python
from crapai.config.loader import load_project_config, resolve_config, parse_cli_overrides
config = load_project_config(Path("project.yaml"))                    # ProjectConfig oder ConfigError
config = resolve_config(path, cli=parse_cli_overrides(["llm.model=x"]), environ=os.environ)
```
* Fehler: `E201` (Pflichtfeld fehlt), `E203` (ungültiger Wert / unbekannte Einstellung); Meldung listet **alle** Probleme als `yaml.pfad: Grund`.
* Umgebungsvariablen: `CRAPAI_<ABSCHNITT>__<SCHLUESSEL>` (z. B. `CRAPAI_LLM__MODEL=gpt-4o`); Wert wird wie YAML typisiert. (Schema ist eine Umsetzungsentscheidung.)
* Rangfolge: CLI > Umgebung > `project.yaml` > `~/.config/crapai/config.yaml` > Standardwerte der Modelle.
* Ein API-Schlüssel kann nicht gespeichert werden; `llm.api_key_env` muss ein gültiger Variablenname sein.

### 3.3 Projektordner (`crapai.project`)

```python
ws = Workspace.create(root)          # legt Ordner und .crapai/version an (leerer/neuer Ordner)
ws = Workspace.open(root)            # prüft Schema-Version; StorageError E404
with ws.lock(): ...                  # ProjectLock; E402 wenn belegt
atomic_write_text(path, text)        # → WriteResult(path, used_alternative)
```
* `ProjectLock`: JSON `{pid, token, started, heartbeat}`; veraltet, wenn Herzschlag > 60 s alt **und** Prozess nicht mehr vorhanden;
  `acquire(take_over_stale=True)` übernimmt. `heartbeat()` alle 10 s (die Schleife gehört zum Screening-Worker, *geplant*).
* `atomic_write`: 5 Wiederholungen à 200 ms bei `PermissionError`, dann `name.YYYYMMDD-HHMMSS.ext` (`used_alternative=True`).
  `write_records` nutzt die Ausweichdatei **nicht** (`allow_alternative=False`): eine gesperrte `records.csv` ist `E401`, ohne Nebendatei und ohne Protokolleintrag.
  Abgeleitete Exporte (später) dürfen `allow_alternative=True` setzen.

### 3.4 Import (`crapai.io`, `crapai.services.importing`)

```python
from crapai.services.importing import ImportRequest, import_source
summary = import_source(Workspace(root), ImportRequest(Path("pubmed.ris"), label="PubMed"))
```
`ImportRequest`: `path, label, encoding, delimiter, sheet, mapping, force`. `ImportSummary`: Zahlen, Format und Begründung,
`column_map`, `notes`, `warnings` (`no_abstracts`, `low_abstract_ratio`, `empty_records`).

Einzelbausteine:

| Funktion | Zweck |
|---|---|
| `io.readers.detect.detect_format(path)` | `DetectionResult(format, confidence, reason, extension_mismatch, encoding, delimiter)` |
| `io.readers.dispatch.read_source(path, ...)` | erkennt und liest; PDF/ZIP → E101 (v1) |
| `read_ris`, `read_nbib`, `read_bibtex`, `read_table` | je `ReadResult(format, records, encoding, notes, column_map, options)` |
| `io.normalize.to_records(result, ImportContext(...))` | `RawRecord` → `Record` |
| `io.records_store.write_records / read_records` | `records.csv`; `backup_dir=` legt Sicherungen an |
| `io.import_log.append_entry / ensure_not_imported` | Protokoll, E106 |
| `prisma.dedup.mark_duplicates(records, DedupConfig(strategy, keep))` | markiert Duplikate; `DedupResult(records, marked, groups, by_method, within_source, across_sources)` |
| `services.dedup.dedup_project(workspace, strategy=None, keep="best")` | liest `records.csv`, markiert, schreibt nach Sicherung; Strategie: Befehlszeile > `project.yaml` > Standard |

`RawRecord.fields` benutzt die internen Spaltennamen; Felder ohne Spalte in `records.csv` (`notes`, `database_name`, `publisher`, `place`,
`edition`, `short_title`, `title_translated` u. a.) landen in `extra_json`, ebenso alle `extra`-Einträge (`ris_<TAG>`, `nbib_<TAG>`, `bib_<name>`, `col_<Spalte>`).

### 3.5 Texte (`crapai.i18n`)

```python
messages = Messages(resolve_language(explicit=None, project_yaml=path))
messages.text("cli.import.done", records=10, file="x.ris", label="A", abstracts=0, total=10)
messages.error_lines(error)          # ["Fehler E106: …", "Warum: …", "Einzelheiten: …", "Was tun: …"]
```
Texte nur in `src/crapai/i18n/texts/en.yaml` und `de.yaml`; Platzhalter benannt (`{count}`), keine Satzverkettung. Neue Schlüssel zuerst
in `en.yaml`, dann `de.yaml` (Schweizer Schreibweise, „Sie“). `tests/unit/test_i18n_parity.py` erzwingt gleiche Schlüssel und Platzhalter;
`i18n/required.py` listet die Schlüssel, auf die Oberfläche und CLI angewiesen sind.

## 4. Datenformate

### 4.1 `data/records.csv` - 40 Spalten (Reihenfolge ist Vertrag)

`study_uid, source_label, source_file, source_row, source_format, record_type, title, abstract, abstract_source, abstract_quality, authors, editors,
year, journal, volume, issue, pages, doi, pmid, pmcid, accession_number, issn_isbn, url, language, keywords, keywords_mesh, publication_types,
is_retracted, is_duplicate, duplicate_of, dedup_method, has_abstract, exclusion_reason, exclusion_details, has_fulltext, fulltext_path,
fulltext_of, zip_member, import_notes, extra_json`

* `source_format`: `ris, bib, nbib, csv, xlsx, pdf`. `record_type`: `journal_article, conference_paper, book, book_chapter, report, thesis, preprint, web, dataset, trial_registry, other`.
* `exclusion_reason` (Plan Kap. 26.3): `DUPLICATE, NO_ABSTRACT, NO_TEXT, ENCRYPTED, EMPTY_RECORD, NOT_SCREENABLE, IMPORT_ERROR, RETRACTED` oder leer. Heute setzt der Import nur `EMPTY_RECORD`.
* `is_duplicate`, `duplicate_of`, `dedup_method` werden von `crapai dedup` gesetzt. `dedup_method`: `doi`, `pmid`, `title_norm`, `title_authors` (`fuzzy` folgt mit T-M2-02). **`pmid` ergänzt die Liste aus Plan Kap. 26.1 und ist von der Projektleitung zu bestätigen.** `abstract_quality` ist noch nicht befüllt *(geplant: T-M2-03)*.
* Ein Datensatz mit Titel und Abstract leer bleibt in der Datei (Markierung, nie Löschen).

### 4.2 `data/records.import.jsonl`

Ein JSON-Objekt je importierter Datei: `schema, timestamp (mit Zeitzone), source_file, sha256, source_label, format, records, abstracts, encoding,
options (delimiter, sheet), column_map, notes, forced`.

### 4.3 `.crapai/lock`, `.crapai/version`

`version`: eine Ganzzahl (heute `1`). `lock`: siehe 3.3. `app.log`: rotierendes Log (1 MB × 3), enthält Vorgänge, keine Datensatzinhalte.

## 5. Einen Reader hinzufügen

1. `SourceFormat` in `io/readers/detect.py` ergänzen und die Erkennung (`_sniff_*`) mit Test erweitern.
2. `io/readers/<name>.py` mit `read_<name>(path, *, encoding=None) -> ReadResult`; interne Spaltennamen verwenden, alles Übrige in `extra`; nie Werte erfinden (kein Platzhalterjahr).
3. In `io/readers/dispatch.py` einhängen und `SOURCE_FORMAT_NAMES` in `io/normalize.py` abbilden (falls neuer Dateiname in `records.csv`, das ist ein **Datenvertrag**, also Rückfrage).
4. Tests mit einer kleinen Fixture (5-20 Datensätze) in `tests/data/`, Sollzahlen in `scripts/build_expected.py` aufnehmen, `EXPECTED.json` neu erzeugen lassen.

## 6. Einen Befehl hinzufügen

Arbeit gehört in `services/`; `cli.py` parst nur Argumente, wählt die Sprache, druckt und übersetzt Fehler in Rückgabecodes (`0/1/2/4`). Texte in beide YAML-Dateien,
`--json` unterstützen (Ergebnis auf stdout, Meldungen auf stderr), Test mit `typer.testing.CliRunner`.

## 7. Qualitätsregeln (Kurzfassung von `AGENTS.md` und `docs/coding/coding_guidelines.md`)

* Code, Docstrings, Logs, Kommentare Englisch; `docs/` Deutsch. Typen überall, Docstrings an öffentlicher API, `logging` statt `print`, `pathlib.Path`.
* Keine Geheimnisse in Dateien oder Logs; keine echten API-Aufrufe in Tests (`MockProvider`, *geplant*).
* Persistierte Namen ändern nur mit Schema-Version und Migration.
* Definition of done: Abnahmekriterien erfüllt, Typen/Docstrings, Tests grün (auch Fehlerpfade), `ruff` und `mypy` sauber, Texte in en+de, Doku und Kartenstatus aktualisiert.
* Lint-Zeilenlänge 100. Portierte Dateien (`enums.py`, `cost/`, `criteria/`, `i18n/`) behalten ihren Stil, bis eine Aufgabe sie überarbeitet (Ausnahmen in `pyproject.toml`).

## 8. Git-Ablauf in diesem Projekt

* Gearbeitet wird direkt auf `main`; **der Projektleiter pusht** (`git push origin main`), der Agent nie.
* Nach jeder fertigen, getesteten Funktion ein Commit mit ausführlicher Nachricht (was, warum, wie getestet), Schema `type(scope): Zusammenfassung (Karten-ID)`.
* Danach wird `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md` mit Datum, Uhrzeit und Kurz-Hash abgehakt.
* Git-Identität nur lokal im Repository; keine globalen Änderungen, kein `--force`, kein `--no-verify`.

## 9. Fehlersuche

| Beobachtung | Ursache / Abhilfe |
|---|---|
| `ModuleNotFoundError: typer` | `pip install -e ".[cli]"` |
| BibTeX-Titel enthalten `{…}` | `pylatexenc` fehlt: `pip install -e ".[import]"` |
| Windows-Konsole zeigt Sonderzeichen falsch | Die CLI stellt stdout auf UTF-8 um; sonst `chcp 65001` |
| `E402` obwohl nichts läuft | veraltete Sperre; nach Bestätigung übernehmbar (`ProjectLock.acquire(take_over_stale=True)`), Datei `.crapai/lock` |
| `E404` bei `status` | Ordner ist kein Projekt (`.crapai/version` fehlt) oder `records.csv` wurde von Hand verändert (`data/.backup/` nutzen) |
| Tests langsam | `pytest -q tests/unit -k "not golden"`; grosse Dateien nur mit `data_large/` |
