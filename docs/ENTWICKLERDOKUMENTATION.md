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
`column_map`, `mapping_source` (`cli`, `project` oder `None`), `notes`, `warnings` (`no_abstracts`, `low_abstract_ratio`, `empty_records`).
Spaltenzuordnung: `--map` > `import.mappings.<Dateiname>` der `project.yaml` > Aliastabelle. Eine unlesbare `project.yaml` blockiert den Import nicht (Warnung im Log).

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
| `prisma.validity.mark_validity(records, ValidityConfig(include_title_only, exclude_retracted))` | setzt `exclusion_reason` (`NOT_SCREENABLE`/`RETRACTED`/`NO_ABSTRACT`), `has_abstract`, `abstract_quality`; `ValidityResult(records, by_reason, quality, valid_for_model)` |
| `services.validity.validate_project(workspace, include_title_only=None, exclude_retracted=None)` | wie `dedup_project`: Sperre, Sicherung, Optionen aus Befehlszeile > `project.yaml` > aus |
| `cost.tokenizers.tokenizer_for(provider, model)` | liefert `TiktokenTokenizer` (OpenAI: `o200k_base`, ältere Namen `cl100k_base`) oder `CharTokenizer(safety_factor=1.10)`; `.count(text)`, `.name`, `.exact`. Ohne installiertes `tiktoken` (Extra `llm-openai`) fällt der OpenAI-Zähler auf Zeichen zurück und meldet `exact=False` |
| `cost.pricing.CsvPriceSource(path).get_price(provider, model)` | `Price(input_per_1k, output_per_1k, currency, valid_from, source)` oder `None`; Gross-/Kleinschreibung egal, Komma oder Punkt als Dezimalzeichen, erste Zeile gewinnt, ungültige Zeilen werden übersprungen (Warnung im Protokoll); fehlende Pflichtspalte oder unlesbare Datei = `E203` |
| `cost.estimator.estimate_run(items, shared_text, tokenizer, price=None, config=None)` | `RunEstimate`: `n_items`, `shared_tokens`, `item_tokens`, `input_tokens`, `output_tokens`, `total_tokens`, `cost`, `cost_low`, `cost_high`, `cost_max` (Worst Case: jede Antwort an der Grenze `llm.max_output_tokens`), `tokenizer`, `exact`. Ohne Preis sind alle Kosten `None`. Kein fester Wert für Volltext: ein längerer Text wird einfach gezählt |
| `cost.duration.estimate_duration(n_items, total_tokens, rpm=, tpm=, max_concurrency=, config=)` | `DurationEstimate(seconds, limited_by)`; `limited_by` ist `rpm`, `tpm`, `latency` oder `none`; Annahme `DurationConfig.seconds_per_request = 3.0`. `format_duration(seconds)` gibt `45 s`, `12 min`, `2 h 05 min`. `decide_confirmation(yes=, interactive=)` gibt `PROCEED`, `ASK` oder `REFUSE` (Regel für `crapai screen`, M3) |
| `services.export.export_records(workspace, fmt, scope=, output=, delimiter=, guard_formulas=)` | schreibt CSV/XLSX/RIS nach `exports/` oder `output`; `ExportSummary(what, format, path, requested_path, records, scope, used_alternative)`; `E203` bei unbekanntem Format/Umfang/Ziel |
| `services.export.export_flow(workspace, output=, mode=)` | schreibt `prisma_flow.json` (`schema`, `generated_at`, `reporting_mode`, `events`, `flow`, `warnings`) |
| `io.writers.tables.write_csv / write_xlsx`, `io.writers.ris.write_ris / record_to_ris` | Formatschreiber; `neutralise_formula(value)` schützt Zellen, die wie Formeln beginnen |
| `services.cost.estimate_project(workspace)` | `ProjectEstimate(estimate, provider, model, max_cost, over_limit, price_file_found, duration)`; zählt die Datensätze ohne `exclusion_reason`; gemeinsamer Anteil aus `project.yaml` (bis der Prompt-Bauer in M3 den genauen Text liefert) |
| `prisma.prefilters.mark_prefilters(records, PrefilterConfig(...))` | `PrefilterResult(records, removed, by_reason, passed_on_missing, skipped)`; setzt `PREFILTER_LANGUAGE`/`_YEAR`/`_TYPE`, berechnet eigene frühere Markierungen neu, ersetzt Gültigkeitsgründe, nie Gründe von Import oder Dedup; `normalize_language`, `languages_of`, `normalize_type` |
| `services.prefilter.prefilter_project(workspace, config=None)` | liest `prefilters` aus `project.yaml` (`config_from_settings`), schreibt `records.csv` unter Sperre mit Sicherung und das Ereignis; `PrefilterSummary` |
| `prisma.events.*` | `PrismaEvent(step, event_type, level, message, source_label, run_id, payload)` (Werte aus `EventType`/`PrismaStep`); Fabriken `source_imported`, `dedup_within_source`, `merge_all_sources`, `dedup_global`, `validity_checked`, `prefilter_applied`, `screening_done`, `warning`; `to_json_line`, `from_json_line`. Tatsachen ohne eigenen Enum-Wert sind `INFO`-Ereignisse mit `payload.kind` (`validity`, `prefilter`) |
| `prisma.flow.build_flow(events, mode, final_included=None)` | `PrismaFlow` (Schlüssel wie `to_prisma_flow` des Vorgängers plus `records_to_screen`, `records_removed_by_prefilter`, `prefilter_reasons`); `to_dict()` ist der Inhalt von `prisma_flow.json` |
| `prisma.flow.validate_flow(flow)` | Liste von `FlowWarning(code, message, payload)`; Codes `DEDUP_AFTER_EXCEEDS_BEFORE`, `MERGED_EXCEEDS_IDENTIFIED`, `ARITHMETIC_MISMATCH`, `SCREENED_EXCEEDS_AVAILABLE`, `FULLTEXT_EXCEEDS_INCLUDED` |
| `services.events.project_flow(workspace, mode=None)` | `(PrismaFlow, Warnungen)`; Modus standardmässig aus `dedup.reporting_mode` |
| `services.preflight.check_file(path, label, ...)` | trockenes Lesen einer Datei vor dem Import, nichts wird geschrieben; `PreflightFileResult(status, issues, message_key, error_code, ...)` mit `PreflightStatus`/`PreflightIssueCode` aus `enums.py` (nur Pfade, keine UI-Typen); wirft nie bei schlechten Dateien |
| `services.preflight.check_project(workspace, update=True)` | optional Dedup + Gültigkeit ausführen, dann `ProjectReport(status, issues, by_reason, sources, ...)` mit `ProjectIssue` (`no_records`, `nothing_to_screen`, `low_abstract_ratio`, `suspect_abstracts`, `retracted_included`, `config_invalid`) |
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
* `exclusion_reason`: ein Grund je Datensatz. Besitz und Vorrang stehen in `prisma/reasons.py` und ADR 0018 (Import: `EMPTY_RECORD`, `IMPORT_ERROR`; Dedup: `DUPLICATE`, ersetzt Gültigkeitsgründe; Gültigkeit: `NOT_SCREENABLE` > `RETRACTED` > `NO_ABSTRACT`). Sollreihenfolge: Import, Dedup, Gültigkeit.
* `abstract_quality`: `ok`, `short` (< 20 Wörter), `suspect_concat` (Wort über 40 Buchstaben oder mittlere Wortlänge über 9); nur ein Hinweis, nie ein Ausschlussgrund.

### 4.2 `data/records.import.jsonl`

Ein JSON-Objekt je importierter Datei: `schema, timestamp (mit Zeitzone), source_file, sha256, source_label, format, records, abstracts, encoding,
options (delimiter, sheet), column_map, notes, forced`.

### 4.2a `data/events.jsonl`

Ein JSON-Objekt je Ereignis, nur anhängen: `schema, event_id, timestamp (UTC), step, event_type, level, message, source_label, run_id, payload`. Schreiber: Import (`SOURCE_IMPORTED`), Dedup (je Quelle `DEDUP_WITHIN_SOURCE`, dann `MERGE_ALL_SOURCES`, `DEDUP_GLOBAL`), Gültigkeit (`INFO` mit `kind: validity`). Eine halb geschriebene letzte Zeile wird ignoriert, eine unlesbare Zeile in der Mitte ist `E404`. Die Zahlen berechnet `prisma.flow.build_flow`; Regeln (Momentaufnahme oder Summe) stehen im Modulkopf.

### 4.3 `.crapai/lock`, `.crapai/version`

`version`: eine Ganzzahl (heute `1`). `lock`: siehe 3.3. `app.log`: rotierendes Log (1 MB × 3), enthält Vorgänge, keine Datensatzinhalte.

## 4a. Tests und Abdeckung

| Prüfung | Datei | Was sie sicherstellt |
|---|---|---|
| Einheitstests je Modul | `tests/unit/test_<modul>.py` | Erfolg, Fehlerfälle, Grenzwerte; `hypothesis` für Eigenschaften |
| Randfälle und Schutzzweige | `tests/unit/test_edge_cases.py` | Zweige, die nur bei Störungen laufen (gesperrte Dateien, beschädigte Eingaben, andere Betriebssysteme), gefunden mit einer Abdeckungsmessung |
| Sollzahlen | `tests/unit/test_*_reader.py`, `tests/integration/` | Zahlen aus `tests/data/EXPECTED.json` (unabhängig berechnet) |
| Dokumente | `tests/unit/test_docs.py` | Handbuch, Entwicklerdokumentation und Architektur stimmen mit CLI und Code überein |
| Docstrings | `tests/unit/test_docstrings.py` | öffentliche API hat Docstring und Rückgabetyp (portierte Module ausgenommen) |
| Texte | `tests/unit/test_i18n_parity.py` | Deutsch und Englisch haben dieselben Schlüssel und Platzhalter |
| Schichten, Lizenz | `test_layering.py`, `test_license.py` | Architekturregel, unveränderter Lizenztext |

**Abdeckung messen** (Zweigabdeckung). `pytest-cov` steht nur im Extra `dev` (`pip install "crapai[dev]"`); wer das Programm normal installiert (`pip install crapai`), bekommt es nicht und braucht es nicht. Gemessen wird nur auf Wunsch: ein normaler Testlauf und der Programmstart messen nichts, `python scripts/qa.py --cov` schaltet es für einen Lauf ein.

```powershell
python -m pip install pytest-cov
python -m pytest -q --cov=crapai --cov-branch --cov-report=term-missing:skip-covered
```

Stand 2026-09-30: **96 %** insgesamt. Der neue Code (Import, Konfiguration, Projekt, Dedup, CLI, Meldungen) liegt bei 99-100 %; die letzten Lücken sind
Zweige, die nur ein anderes Betriebssystem oder eine Unterbrechung in einem bestimmten Augenblick erreichen. Die Restlücke liegt in den **übernommenen** Modulen
`criteria/template.py` und `legacy.py` (`cost/*` ist seit T-M2-05 neu geschrieben und zu 100 % abgedeckt). Ziel laut Plan Kap. 33.8: mindestens 80 % Zeilen und 70 % Zweige im Kern.

## 5. Einen Reader hinzufügen

1. `SourceFormat` in `io/readers/detect.py` ergänzen und die Erkennung (`_sniff_*`) mit Test erweitern.
2. `io/readers/<name>.py` mit `read_<name>(path, *, encoding=None) -> ReadResult`; interne Spaltennamen verwenden, alles Übrige in `extra`; nie Werte erfinden (kein Platzhalterjahr).
3. In `io/readers/dispatch.py` einhängen und `SOURCE_FORMAT_NAMES` in `io/normalize.py` abbilden (falls neuer Dateiname in `records.csv`, das ist ein **Datenvertrag**, also Rückfrage).
4. Tests mit einer kleinen Fixture (5-20 Datensätze) in `tests/data/`, Sollzahlen in `scripts/build_expected.py` aufnehmen, `EXPECTED.json` neu erzeugen lassen.

## 5a. Statuswerte des Preflights

`ERROR`: keine Datensätze oder nichts geht ans Modell (`no_records`, `nothing_to_screen`). `WARNING`: mindestens ein Hinweis (weniger als 60 % Abstracts in einer Quelle, verdächtige Abstracts,
zurückgezogene Studien im Lauf, ungültige `project.yaml`). Rückgabecodes von `crapai check`: 0, 4, 1. Die Schwelle 60 % steht in `PreflightConfig`.
Die Codes `ProjectIssue` sind eigene Werte; die persistierten Werte von `PreflightIssueCode` in `enums.py` wurden nicht verändert.

## 5b. Regeln für Fehlerbehandlung, Protokoll und Dateien (nach ADR 0020)

Wer Code ergänzt, hält diese Regeln ein; `tests/unit/test_*review_fixes.py` und `test_*robustness.py` sichern sie ab.

* **Kein roher Python-Fehler an der Oberfläche.** Dateizugriffe fangen `OSError`, `UnicodeDecodeError` und `csv.Error` und machen daraus einen `SaraError` mit Code und Hinweis (`E101` Datei lesen, `E103` Kodierung, `E401`/`E403` Schreiben, `E404` Projektdatei unbrauchbar). Die Befehle fangen den Rest an der Grenze (`_fail`) und geben Rückgabecode 2 (`E999`).
* **Protokoll:** Fehlerpfade schreiben eine `logger.error`- oder `logger.warning`-Zeile mit **Code und Art** des Fehlers (`type(exc).__name__`), nie Titel, Abstracts oder Schlüssel. Erfolgspfade schreiben eine `logger.info`-Zeile mit Zahlen. Das Protokoll liegt in `.crapai/app.log` (1 MB × 3); kann es nicht geöffnet werden, läuft der Befehl trotzdem.
* **Dateien, die wachsen** (`records.import.jsonl`, `events.jsonl`) schreibt nur `project.atomic.append_lines`: abgerissener Schluss wird abgeschnitten, dann angehängt und mit `fsync` gesichert. Ganze Dateien schreibt nur `atomic_write*` (eindeutiger Temp-Name je Aufruf und Thread; bei gesperrtem Ziel eine Ersatzdatei mit freiem Namen).
* **Sperre:** Wer mehrere Schritte zusammen ausführt, hält **eine** Sperre (`with workspace.lock():`) und ruft die `apply_*`-Funktionen, die selbst keine Sperre nehmen (`apply_dedup`, `apply_prefilters`, `apply_validity`). Unlesbare Sperre = in Benutzung, nie veraltet; Entfernen nur über `ProjectLock.remove_stale`.
* **Ereignisse** (`services/events.py`): `record_*` liefern `True`, wenn das Ereignis in der Datei steht (auch unverändert übersprungen), sonst `False`; der Aufrufer meldet die Lücke als Warnung. Schreibt ein Schritt eine Momentaufnahme, steht die Regel "veraltet" in `prisma/flow.py` (Modulkopf).
* **JSON-Modus:** stdout enthält genau ein JSON-Dokument, alle Meldungen gehen nach stderr; Fehler erscheinen zusätzlich als `{"error": {"code", "message", "hint"}}`.
* **Code, Kommentare, Docstrings und Protokolltexte sind Englisch**; Benutzertexte stehen in `i18n/texts/{en,de}.yaml`, Dokumente in `docs/` sind Deutsch. `ruff format` (Zeilenlänge 100) ist Pflicht und wird in der CI geprüft.

## 5c. Die Oberfläche (`crapai.ui`)

Drei Schichten, damit fast alles ohne Streamlit testbar ist:

1. `ui/viewmodels.py` und `ui/context.py`: reine Entscheidungen (Stand der Schritte, Kennzahlen, Sperrgründe, Liste der letzten Projekte). Test: `tests/unit/test_ui_logic.py`.
2. `ui/actions.py`: jede Aktion liefert ein `Outcome` (Wert **oder** `ErrorReport`); `guarded()` fängt alle Ausnahmen, protokolliert sie (Code und Meldung, bei Unerwartetem mit Traceback) und übersetzt sie mit `Messages.error_report`. Hochgeladene Dateien werden nur unter ihrem Basisnamen gespeichert (kein Pfadausbruch), doppelte Namen nummeriert.
3. `ui/pages/*.py`: nur Zeichnen, `render(st, ctx)`; `st` wird übergeben, nicht importiert. Test: `tests/ui/test_app.py` mit `streamlit.testing.v1.AppTest` (wird ohne Streamlit übersprungen).

Regeln: Texte stehen unter `ui.*` in `i18n/texts/{en,de}.yaml` (Paritätstest); bereits vorhandene Texte der Befehlszeile (`cli.check.*`, `errors.*`) werden wiederverwendet. Ein Seitenwechsel aus einer Seite heraus setzt `session_state["goto"]` (das Navigations-Widget darf erst beim Aufbau gesetzt werden). Der Start (`crapai ui`) übergibt den Ordner über die Umgebungsvariable `CRAPAI_UI_PROJECT` und bindet an `127.0.0.1` mit abgeschalteter Nutzungsstatistik (ADR 0010). Streamlit ist nur im Extra `ui` (`pip install "crapai[ui]"`).

## 5d. Arbeitsablauf der Entwicklung

`python scripts/qa.py` führt die Gates in der Reihenfolge der CI aus (Lint, `ruff format --check`, `mypy`, alle Tests ohne `live`) und bricht beim ersten Fehler ab; `--fix` lässt `ruff` vorher reparieren und formatieren, `--fast` setzt einen festen Hypothesis-Startwert und stoppt beim ersten Fehler, `--ci` setzt die Umgebung von GitHub Actions. Die Tests sind von der Maschine unabhängig (`tests/conftest.py`): feste Terminalausgabe, ein eigenes Heimverzeichnis je Test (die echte Liste der letzten Projekte bleibt unberührt), kein `fsync` und keine Wartezeiten bei Wiederholungen (`atomic.FSYNC`, `atomic.DEFAULT_DELAY_S`).

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
| CI rot, lokal grün | Die CI-Umgebung unterscheidet sich (Umgebungsvariablen, Farben, Betriebssystem). So nachstellen: `$env:GITHUB_ACTIONS="true"; $env:CI="true"; python -m pytest -q`, zusätzlich in einem frischen Klon mit frischem `venv`. Bekannter Fall: Typer erzwingt auf GitHub farbige Hilfetexte; `tests/conftest.py` neutralisiert das, `test_docs.py` entfernt Farbcodes vor dem Auswerten |
| Tests langsam | `pytest -q tests/unit -k "not golden"`; grosse Dateien nur mit `data_large/` |
