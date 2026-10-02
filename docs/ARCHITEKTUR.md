# ARCHITEKTUR.md - Aufbau und Software-Architektur von Critical Apprais.AI

Stand: 2026-10-02, Version 0.0.1. Umgesetzt: Meilenstein A (Import), M2 (Aufbereitung: Dedup, Vorfilter inkl. Stichwörter,
Gültigkeit, Kosten), M3 (Screening-Kern: Anbieter, Prompt, Antwortprüfung, Engine), die lokale Oberfläche (`crapai ui`),
Ergebnistabelle und Auswertung, der Lauf-Vergleich (`crapai compare-runs`) und das Klären von Uneinigkeit zwischen Läufen
(`crapai adjudicate`, `crapai discuss`, ADR 0024/0025). Offen: Vergleich mit menschlichen Entscheidungen, PRISMA-Grafik (PNG/SVG).
Zielgruppe: Entwickler:innen und Prüfende, die verstehen wollen, wie das Programm gebaut ist und warum.
Die vollständige Spezifikation ist `docs/PROJEKTPLAN.md`; diese Datei beschreibt den **tatsächlichen Stand des Codes**
und kennzeichnet Geplantes ausdrücklich. Bedienung: `docs/BENUTZERHANDBUCH.md`. Programmierung: `docs/ENTWICKLERDOKUMENTATION.md`.
Laufend aktueller, verlässlicher Stand (Testzahl, nächster Schritt): `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`.

## 1. Leitgedanken

| Grundsatz | Bedeutung im Code |
|---|---|
| **Der Projektordner ist die Datenbank** | Keine Datenbank, kein Server, keine Konten. Alles liegt in Dateien (CSV, JSONL, YAML). ADR 0001 |
| **Lokal** | Nach aussen geht nur der Aufruf an den Modellanbieter (Screening, Schiedsrichter, Diskussion). Keine Telemetrie |
| **Nichts still verlieren** | Duplikate und Datensätze ohne Abstract werden *markiert*, nie gelöscht. Unbekannte Felder wandern in `extra_json` |
| **Nie ein Label aus einer unbrauchbaren Antwort** | Fehlerhafte Modellantworten erhalten einen Status (`parse_error` u. a.), nie `INCLUDE` (Lehre L4) |
| **Alles über `study_uid`** | Jeder Datensatz bekommt beim Import eine stabile ID; nie Zeilenpositionen als Schlüssel (Lehre L1) |
| **Persistierte Namen sind Verträge** | Spaltennamen, Enum-Werte, JSON-Schlüssel, Dateinamen ändern sich nur mit Versionssprung und Migration |
| **Vorschläge, keine Entscheidungen** | Die Software ersetzt keine menschliche Prüfung |

## 2. Schichten

```
Bedienung        cli.py (typer)                      ui/ (Streamlit, siehe unten)
                    │  ruft
Dienste          services/importing.py   services/project.py   services/dedup.py   services/validity.py   services/preflight.py
                 services/cost.py   services/events.py   services/prefilter.py   services/export.py   services/screening.py
                 services/results.py   services/resolution.py
Oberfläche       ui/ (Streamlit: viewmodels, actions, context, app, pages/ - inkl. Lauf, Export, Auswertung)   logging_setup.py
                    │  ruft
Fachkern         io/ (readers, normalize, records_store, import_log, writers)
                 config/ (Modelle, Loader, Overrides)   project/ (Workspace, Lock, atomares Schreiben)
                 i18n/ (Texte, Meldungen)    errors.py   criteria/  cost/  enums.py  legacy.py
                 prisma/ (dedup, prefilters, validity, events, flow)   llm/ (base, resilience, mock, openai)
                 prompts/ (builder, resolution)   screening/ (answer, store, engine)   stats/ (results, agreement)
                    │  spricht mit der Aussenwelt nur über
Ports/Adapter    `llm.base.LLMProvider` (Protokoll, umgesetzt: Mock, OpenAI/-kompatibel); Uhr/Zufall/Schlaf als
                 injizierbare Parameter statt eigener Klassen (`clock`, `sleep`, `now`, `rng` in Engine/Lock/Atomic/Resilience);
                 kein eigenes FileStore-/SecretStore-/EventSink-Protokoll (Dateizugriff läuft direkt über `pathlib`/`project.atomic`)
```

**Regel 1: Pfeile zeigen nur nach unten.** Der Fachkern importiert weder `streamlit`, `typer` noch ein LLM-SDK
(`openai`, `anthropic`) und nicht die Schichten `cli`, `ui`, `services`, `adapters`.
**Durchgesetzt:** `tests/unit/test_layering.py` liest den Quelltext mit `ast` und schlägt fehl, wenn die Regel verletzt wird
(auch bei Importen innerhalb von Funktionen). Der Test prüft sich selbst mit einem künstlichen Verzeichnis.

Diensteschicht (`services/`) darf den Kern verwenden, aber nicht `typer`; nur `cli.py` kennt `typer`.
So bleibt der Kern ohne Oberfläche testbar und später von Streamlit und CLI gemeinsam nutzbar (ADR 0013).

## 3. Module (Stand heute)

| Modul | Aufgabe | Wichtige Bestandteile |
|---|---|---|
| `errors` | Fehlerhierarchie | `SaraError` (Code, Meldung, Hinweis, Details) und Unterklassen `ConfigError`, `ImportFailed`, `ProviderError` (+ `AuthError`, `RateLimited`, `TransientError`, `ContextTooLong`, `ContentRefused`, `QuotaExceeded`), `ParseError`, `StorageError`, `EvaluationError` |
| `config.models` | Gültigkeit von `project.yaml` | Pydantic-Modelle, `extra="forbid"`, kein Feld für Schlüssel, Fehlertexte ohne den falschen Wert |
| `config.loader` | Laden und Zusammenführen | `load_project_config`, `resolve_config` (Rangfolge CLI > Umgebung > Projekt > Benutzer > Standard), `env_overrides`, `parse_cli_overrides` |
| `config.templates` | Vorlagen | `blank.yaml`, `demo.yaml` (als Paketdaten) |
| `project.atomic` | Sicheres Schreiben | `atomic_write`: Temp-Datei, `fsync`, `os.replace`, Wiederholung bei Sperre, Ausweichdatei |
| `project.lock` | Ein Schreiber je Projekt | `ProjectLock` mit Herzschlag, Übernahme veralteter Sperren |
| `project.workspace` | Ordnerstruktur | `Workspace.create/open`, Schema-Version, Warnung bei OneDrive/Dropbox |
| `prisma.reasons` | Katalog der Ausschlussgründe und wer sie setzen darf | `VALIDITY_REASONS`, `REASON_*` (ADR 0018) |
| `prisma.events` | PRISMA-Ereignisse: Modell `PrismaEvent` und reine Fabrikfunktionen (Import, Dedup je Quelle, Zusammenführung, globales Dedup, Gültigkeit, Vorfilter, Screening); Zeilenformat JSON | `PrismaEvent`, `source_imported`, `dedup_within_source`, `dedup_global`, `to_json_line` |
| `prisma.flow` | Zahlen des PRISMA-2020-Flussdiagramms, **abgeleitet** aus den Ereignissen (Portierung von `to_prisma_flow` und `validate_rollup`, beide Berichtsmodi) | `build_flow`, `validate_flow`, `PrismaFlow` |
| `services.events` | Ereignisdatei `data/events.jsonl` lesen und anhängen, die Ereignisse von Import, Dedup und Gültigkeit schreiben, Fluss eines Projekts | `append_events`, `read_events`, `project_flow`, `record_dedup` |
| `prisma.prefilters` | deterministische Vorfilter vor dem Modell: Sprache (ISO 639-2), Jahr, Publikationstyp, optional Stichwörter (Title/Abstract/Keywords als ein Text, Positiv- und Negativliste); fehlende Angaben nach `on_missing` | `mark_prefilters`, `PrefilterConfig`, `normalize_language` |
| `services.prefilter` | Vorfilter aus `project.yaml` im Projekt anwenden, Ereignis schreiben | `prefilter_project` |
| `prisma.validity` | Gültigkeit: fehlende Abstracts, Front-Matter, zurückgezogene Studien, Abstract-Qualität | `mark_validity`, `ValidityConfig`, `classify_abstract`, `is_not_screenable` |
| `services.validity` | Gültigkeit im Projekt anwenden | `validate_project` |
| `cost.tokenizers` | lokale Token-Zähler: `tiktoken` (OpenAI, genau) oder Zeichenzähler mit Sicherheitszuschlag; jeder Zähler meldet `name` und `exact` | `tokenizer_for`, `CharTokenizer`, `TiktokenTokenizer` |
| `cost.pricing` | Preisquellen: editierbare `pricing.csv` (Preis je 1000 Token, Datum, Quelle) oder statisch; unbekanntes Modell = kein Preis | `CsvPriceSource`, `StaticPriceSource`, `Price` |
| `cost.estimator` | Schätzung eines Laufs aus den **echten** Texten (Titel + Abstract je Datensatz, gemeinsamer Anteil einmal gezählt), Kostenband und Worst Case; ohne I/O | `estimate_run`, `RunEstimate`, `build_shared_payload` |
| `cost.duration` | Dauerschätzung aus rpm, tpm und Parallelität; Bestätigungsregel vor einem Lauf (`--yes` oder Terminal) | `estimate_duration`, `decide_confirmation` |
| `config.overrides` | Einstellungen ausserhalb von `project.yaml`: Überschreibdatei `project.overrides.yaml`, Quelle jedes Wertes, `set`/`reset` mit Prüfung vor dem Schreiben | `set_values`, `reset_values`, `effective_settings` |
| `config.profiles` | Wiederverwendbare Settings-Profile (Ziele, Kriterien, Screening, LLM) speichern/laden, unabhängig vom Projekt (`~/.config/crapai/profiles/`); Laden schreibt in `project.overrides.yaml`, nie in `project.yaml` (ADR 0027) | `SettingsProfile`, `save_profile`, `load_profile`, `apply_profile`, `list_profiles`, `delete_profile` |
| `ui.settings_form` | die in der Oberfläche änderbaren Einstellungen als Daten; nur Unterschiede werden gespeichert | `SECTIONS`, `changes`, `parse_value` |
| `logging_setup` | Protokoll für Befehlszeile und Oberfläche: ein Format mit Sitzungskennung, Schutz vor Schlüsseln, Stufe aus Option oder `CRAPAI_LOG_LEVEL`, rotierende Projektdatei, tolerant gegen nicht schreibbare Dateien | `attach_project_log`, `enable_console_log`, `redact`, `read_log_tail` |
| `ui.viewmodels` | Was die Oberfläche zeigt, ohne Streamlit: Schrittleiste (Schritt „Lauf“ folgt dem neuesten Lauf), Kennzahlen, zuletzt verwendete Projekte, Sicht auf einen Lauf aus `manifest.json` (Fortschritt, veraltet, fortsetzbar) | `build_stepper`, `load_overview`, `RecentProjects`, `RunView`, `load_run_views`, `failed_results` |
| `ui.actions` | Was ein Klick tut: ruft die Dienste, macht jeden Fehler zu einem `ErrorReport` (kein `try` in den Seiten) | `guarded`, `open_project`, `prepare_uploads`, `import_prepared`, `run_check`, `run_export`, `start_run` (startet `python -m crapai screen` als eigenen Prozess), `control_run`, `estimate_run`, `compare_runs` |
| `stats.results` | Ergebnistabelle eines Laufs (eine Zeile je Datensatz mit Ergebniskategorie INCLUDE/EXCLUDE/UNCERTAIN/ERROR/PRE_EXCLUDED/NOT_SCREENED), exportierte CSV/XLSX-Dateien wieder einlesen und prüfen, Zahlen für die Diagramme (je Quelle, Jahr, Abstract-Länge, Status, Markierungen, Kosten); Vergleichstabelle mehrerer Läufe (eine Spaltengruppe je Lauf, `agreement`-Spalte); rein, ohne Dateizugriff | `build_table`, `read_table_file`, `analyse`, `Analysis`, `RESULT_COLUMNS`, `compare_table`, `compare_columns` |
| `stats.agreement` | Test-Retest/Inter-Rater-Übereinstimmung mehrerer Läufe (Plan Kap. 14.1): paarweise Übereinstimmung und Cohens Kappa je Lauf-Paar (je eigene Schnittmenge entschiedener Datensätze), Fleiss' Kappa über alle Läufe zusammen, Einstufung nach Landis & Koch, uneinige Datensätze; rein, ohne Dateizugriff | `compare`, `pairwise`, `cohens_kappa`, `fleiss_kappa`, `landis_koch_label`, `ComparisonSummary` |
| `services.results` | Ergebnistabelle des Projekts aus Datensätzen und dem letzten Ergebnis je Datensatz eines Laufs; Export als CSV/XLSX in `exports/`; Vergleich mehrerer Läufe und dessen Export | `results_table`, `export_results`, `runs_with_results`, `compare_runs`, `export_comparison` |
| `ui.charts` | Diagramme als Vega-Lite-Beschreibungen (Ring, Balken, gestapelte Balken, Histogramm, Streudiagramm, Boxplot, gruppierte Balken je Lauf) in den Farben des gewählten Designs; ohne Zeichenpaket | `donut`, `bars`, `stacked`, `histogram`, `scatter`, `boxplot`, `run_bars`, `run_scale`, `CHART_COLORS`, `RUN_COLORS` |
| `ui.definition` | Projektbeschrieb, Forschungsfragen und Kriterien als Daten für das Formular; prüft sie und macht daraus die Einstellungen für `project.overrides.yaml` | `Definition`, `load_definition`, `problems`, `to_settings`, `framework_elements` |
| `ui.theme` | Aussehen: heller und dunkler Farbsatz (jede Text/Hintergrund-Paarung mindestens 4,5:1 Kontrast, per Test geprüft), kleine und grosse Schrift, Stylesheet daraus; gespeicherte Wahl (`ui_prefs.json`: Sprache, Design, Schriftgrösse) | `PALETTES`, `build_css`, `contrast_ratio`, `UiPrefs` |
| `ui.kit` | Hülle um Streamlit: eigene Hinweisboxen (Farben aus dem gewählten Design) und automatischer Hilfetext (`ui.tip.<id>`) für jedes Bedienelement mit `key`; meldet Elemente ohne Hilfetext (Test) | `Themed`, `help_id`, `notice_html` |
| `ui.context` | Gemeinsamer Zustand einer Sitzung und Sperrgründe der Seiten | `Context`, `lock_reason` |
| `ui.app`, `ui.streamlit_app` | Einstiegspunkt: Seitenaufbau, gespeicherte Wahl (Sprache, Design, Schrift), Seitenleiste (Titel, Anzeige-Schalter, Menü aus Schaltflächen in Gruppen), Statuszeile, Weiterleitung | `main` |
| `ui.pages.*` (`start`, `overview`, `project`, `data`, `check`, `run`, `flow`, `export`, `results`, `settings`, `help`, `common`) | je eine Seite, nur Zeichnen; `render(st, ctx)` | `render` |
| `io.writers.tables`, `io.writers.ris`, `io.writers.bibtex`, `io.writers.nbib` | Export-Dateien: CSV (UTF-8 mit BOM, Formelschutz), XLSX (fixierte Kopfzeile, Steuerzeichen entfernt), RIS/BibTeX/NBIB (für Literaturverwaltung, Screening-Vermerke in Notizfeld bei RIS/BibTeX, NBIB ohne - kein passendes Feld); alle atomar geschrieben | `write_csv`, `write_xlsx`, `write_ris`, `write_bibtex`, `write_nbib` |
| `io.writers.prisma_image` | PRISMA-2020-Flussdiagramm als PNG/SVG (Kästen mit Pfeilen, Zahlen aus `PrismaFlow`), reines `matplotlib` ohne `pyplot` (kein globaler Zustand); braucht das Extra `stats` | `write_prisma_image` |
| `io.writers.docx_report` | Lesbarer Word-Zusammenfassungsbericht (Ziele, Kriterien, PRISMA-Fluss, Screening-Ergebnisse des neusten Laufs); nichts Neues berechnet, nur bereits vorhandene Zahlen; braucht das neue Extra `report` (ADR 0028) | `build_report`, `write_docx_report` |
| `services.export` | Datensätze (Umfang alle/screenable/excluded) und PRISMA-Fluss exportieren, ohne das Projekt zu ändern; gesperrte Zieldatei ergibt eine Ersatzdatei | `export_records`, `export_flow`, `ExportSummary` |
| `services.cost` | Schätzung für ein Projekt: zählt die Datensätze ohne Ausschlussgrund, liest `pricing.csv` des Projekts, vergleicht den Worst Case mit `limits.max_cost`; schreibt nichts | `estimate_project`, `ProjectEstimate` |
| `__main__` | Einstieg `python -m crapai` (wie der Befehl `crapai`); die Oberfläche startet damit den Screening-Prozess getrennt vom Browser (ADR 0006) | `main` |
| `cli_progress` | Fortschrittsbalken von `crapai screen`: eine überschriebene Zeile auf dem Terminal, sonst gelegentliche Textzeilen; ein kaputter Ausgabekanal stoppt nie einen Lauf | `ProgressPrinter`, `format_line`, `render_bar` |
| `llm.base` | Schnittstelle zwischen Engine und Anbieter: Anfrage, Antwort, Fähigkeiten, `LLMProvider`-Protokoll; Fehlerklassen tragen die Wiederholungsregel (E301/E302/E303/E305/E306/E307); kein Netz, kein SDK | `LLMRequest`, `LLMResponse`, `Capabilities`, `LLMProvider`, `retry_after_of` |
| `llm.resilience` | Wiederholen mit Backoff und `Retry-After`, gleitendes Fenster für Anfragen/Tokens pro Minute, adaptive Parallelität (halbieren bei 429, langsam steigern), Sicherung bei Fehlern in Folge; Uhr und Schlaf einsetzbar (Tests ohne Wartezeit) | `RetryPolicy`, `call_with_retry`, `RateLimiter`, `AdaptiveConcurrency`, `CircuitBreaker` |
| `llm.mock_provider` | Anbieter ohne Netz und ohne Schlüssel mit den 15 Fehlerszenarien S1-S15 (deterministisch); die ganze Engine wird dagegen getestet | `MockProvider`, `SCENARIOS`, `answer_json` |
| `llm.openai_provider` | OpenAI und OpenAI-kompatible Dienste (SwissGPT): Fehlerübersetzung in die eigenen Klassen, SDK-Wiederholungen aus, Schlüssel nie in Meldungen oder Logs | `OpenAICompatibleProvider`, `translate` |
| `prompts.resolution` | Prompts, um eine Uneinigkeit zwischen Läufen zu klären: `build_adjudication_prompt` (Schiedsrichter sieht Datensatz, Kriterien und jede Meinung), `build_discussion_prompt` (ein Teilnehmer sieht die Gegenmeinung); gleiches Antwortschema wie beim Screening (ADR 0025) | `Opinion`, `DisputedItem`, `build_adjudication_prompt`, `build_discussion_prompt` |
| `prompts.builder` | Prompt je Datensatz: stabiler Anfang (System, Projekt, Kriterien, Anweisungen) und `<record>`-Block (Title/Abstract, optional Keywords per `screening.include_keywords_in_prompt`), Fingerabdruck des stabilen Teils (Keywords im Datensatz-Teil ändern ihn nicht); Varianten aus YAML (Paket und Projekt); `build_fulltext` für `project.mode: fulltext` (Volltext statt Abstract im Block, optional Kriterien nach dem Text wiederholt, ADR 0026) | `PromptBuilder`, `PromptVariant`, `builder_for`, `load_variant`, `hash_text` |
| `prompts.fulltext_sections` | Abschnitte eines Volltexts erkennen (Methods/Results/Discussion u. a., anhand von Überschriftzeilen); Grundlage für die Strategien `sections`/`map_reduce` (ADR 0026) | `split_sections`, `methods_results_discussion` |
| `screening.fulltext` | Volltext ins Kontextfenster einpassen: `truncate` (kürzen), `sections` (nur Methods/Results/Discussion, sonst Rückfall auf `truncate`); `map_reduce` wird hier nur in Stücke geteilt, die Engine macht daraus mehrere Modellaufrufe (ADR 0026) | `prepare_fulltext`, `chunk_for_map_reduce`, `PreparedFulltext` |
| `screening.answer` | Antwort des Modells prüfen: Schema, Entscheidung zuletzt, Gegenprobe aus den Urteilen, Zitate im Datensatz, altes XXX/YYY-Format; unlesbar ist ein Fehler, nie ein Einschluss | `ANSWER_SCHEMA`, `parse_answer`, `derive_decision`, `check_quotes`, `parse_legacy` |
| `screening.store` | Dateien eines Laufs: `manifest.json` (atomar), `screening.jsonl` (nur anhängen, letzte Zeile je Datensatz gilt), `control.json` (Pause/Stopp von aussen); `ResultRow` trägt auch die sonst ungenutzten Felder `source_decisions`/`consensus`/`rounds_used`/`tie_break`/`history` eines Schiedsrichter-/Diskussionslaufs (ADR 0025) | `RunStore`, `Manifest`, `ResultRow`, `RunState`, `BatchInfo` |
| `screening.engine` | Verarbeitung in Päckchen mit Prüfung auf der Platte, Arbeiter, Fristen, Fehlerquote je Päckchen, Sicherung, Kostenlimit, Schonfrist beim Stopp; jeder Halt hat einen Zustand und einen Code | `ScreeningEngine`, `EngineSettings`, `PlanItem`, `Progress`, `RunSummary` |
| `services.screening` | Lauf planen, starten, fortsetzen: Sperre, `plan.json`, Fingerabdruck der Einstellungen (E204), Stichprobe, Strg+C, PRISMA-Ereignis nur für vollständige Läufe | `screen_project`, `RunOptions`, `RunResult`, `make_provider`, `list_runs`, `find_run`, `request_control` |
| `services.resolution` | Eine Uneinigkeit zwischen zwei oder mehr abgeschlossenen Läufen klären: `disputed_items` (welche Datensätze, welche Meinungen), `adjudicate_project` (ein Schiedsrichter-Modell, die aktuellen `llm:`-Einstellungen), `discuss_project` (die ursprünglichen Modelle jedes Laufs, aus deren eigenem Manifest rekonstruiert, bis zu `discussion.max_rounds` Runden, danach `discussion.tie_break`); gespeichert wie ein gewöhnlicher Lauf (`runs/<lauf-id>/`, `kind` `adjudicate`/`discuss`), ändert nie `records.csv`; `resolvable_runs` und `services.results.runs_with_results` halten solche Läufe aus der gewöhnlichen Auswertung heraus (ADR 0025) | `disputed_items`, `adjudicate_project`, `discuss_project`, `participant_config`, `ResolutionOptions`, `ResolutionResult` |
| `services.preflight` | Vorprüfung: eine Datei vor dem Import, das Projekt vor dem Lauf | `check_file`, `check_project`, `PreflightFileResult`, `ProjectReport`, `ProjectIssue` |
| `prisma.dedup` | Duplikate markieren (nicht löschend) | `mark_duplicates`, `DedupConfig`, `DedupResult`, `normalize_title`; Strategien `doi_or_title`, `strict_ids`, `title`, `title_authors` |
| `services.dedup` | Duplikate im Projekt markieren | `dedup_project` (Sperre, Sicherung, atomares Schreiben) |
| `io.readers.detect` | Formaterkennung | `detect_format` (Inhalt vor Endung), `SourceFormat` |
| `io.readers.ris` / `nbib` / `bibtex` / `tabular` | Reader | liefern `ReadResult` mit `RawRecord`-Objekten |
| `io.readers.base` | gemeinsame Typen | `RawRecord`, `ReadResult`, `decode_text` (Kodierungskette) |
| `io.readers.dispatch` | ein Einstieg | `read_source` |
| `io.readers.pdf_zip` | Volltext-PDFs aus einem ZIP lesen (nie entpackt, Zip-Slip-Schutz), Qualität bewerten (`pages`/`chars`/`chars_per_page`/`has_text_layer`), Text bereinigen (Trennstriche, Ligaturen, Kopf-/Fusszeilen, Literaturverzeichnis abschneiden); ADR 0026 | `extract_pdf_zip`, `extract_one`, `PdfDocument`, `PdfZipResult` |
| `io.fulltext_link` | Eine gefundene PDF per DOI, sonst per Titel (wie `prisma.dedup`) einem bestehenden Datensatz zuordnen; ein Treffer wird eine **neue, zusätzliche** Zeile (`fulltext_of`, `zip_member`), kein Treffer erscheint in `reports/unmatched_pdfs.csv`, nie stillschweigend verworfen; ADR 0026 | `link_fulltext`, `write_unmatched_report`, `FulltextLinkResult` |
| `io.normalize` | Bereinigung | `clean_text`, `normalize_doi`, `coerce_year`, `normalize_list`, `to_record(s)` |
| `io.records_store` | `records.csv` | `Record` (40 Spalten), `write_records`, `read_records`, Sicherungen |
| `io.import_log` | Import-Protokoll | SHA-256, `ImportLogEntry`, `ensure_not_imported` (E106) |
| `services.importing` | Import ablaufen lassen; ein ZIP mit PDFs geht an `io.fulltext_link` statt an die üblichen Leser (ADR 0026) | `import_source` |
| `services.project` | Projekt anlegen, Status | `create_project`, `project_status` |
| `i18n`, `i18n.messages` | Texte und Meldungen | `I18n` (geschichtet: Python-Rückfall → en → Sprache), `Messages` (Fehlerbericht: Fehler CODE, Warum, Einzelheiten, Was tun), `resolve_language`, `required_keys` |
| `cli` | Befehle | `init`, `import`, `status` |
| `enums`, `criteria`, `cost`, `legacy` | aus dem Vorgänger übernommen | siehe `docs/MIGRATION.md` |

## 4. Datenfluss beim Import

```
 Exportdatei (RIS/NBIB/BibTeX/CSV/XLSX)
        │  1. SHA-256 bilden; schon importiert? → E106 (ausser --force)
        ▼
 detect_format ─ Inhalt zuerst, Endung danach ─► SourceFormat, Konfidenz, Begründung
        │  2. LESEN, bevor irgendetwas geschrieben wird
        ▼
 Reader (ris | nbib | bibtex | tabular)  ─►  ReadResult[ RawRecord(fields, extra, notes) ]
        │  3. Original nach sources/ kopieren (nie überschreiben, per Hash geprüft)
        ▼
 to_records: Text säubern (NFC, Steuerzeichen, Entities), DOI/Jahr/Listen normalisieren,
             study_uid vergeben, EMPTY_RECORD markieren, Restfelder → extra_json
        │  4. records.csv atomar neu schreiben (vorher Sicherung in data/.backup/)
        ▼
 data/records.csv        5. Import-Log-Eintrag zuletzt: er markiert den Import als vollständig
 data/records.import.jsonl
```

Der Ablauf hält den **Projektordner** unter der Projektsperre (`.crapai/lock`). Bricht das Programm mitten drin ab, ist
höchstens ein Import nicht protokolliert (die Datensätze stünden dann schon in `records.csv`); nie ist `records.csv` halb geschrieben.

## 5. Projektordner (Datenvertrag)

```
mein-review/
├─ project.yaml                Projekt, Kriterien, LLM-Einstellungen (nie ein Schlüssel)
├─ sources/                    Originaldateien, unverändert (Kopie beim Import)
├─ data/
│  ├─ records.csv              ALLE Datensätze, 40 Spalten (Quelle der Wahrheit)
│  ├─ records.import.jsonl     ein Eintrag je importierter Datei (Hash, Zahlen, Zuordnung)
│  ├─ events.jsonl             PRISMA-Ereignisse (nur anhängen): Quelle der Flusszahlen
│  └─ .backup/                 die letzten 5 Sicherungen von records.csv
├─ runs/<lauf-id>/             ein Ordner je Screening-Lauf: manifest.json, screening.jsonl, plan.json, control.json
├─ human/  reports/  prompts/  [geplant/optional]
└─ .crapai/                      version (Schema), lock, app.log
```

Formatregeln (Plan Kap. 25.7): CSV nach RFC 4180, UTF-8 **ohne** BOM, Zeilenende `\n`, Komma, minimales Quoting, leerer Wert = null,
Booleans `true`/`false`, Listen `"A; B"`, `extra_json` als kompaktes JSON. JSONL: ein Objekt je Zeile, kompakt, `ensure_ascii=False`,
nach jeder Zeile `flush` + `fsync`; eine kaputte **letzte** Zeile wird ignoriert, eine kaputte Zeile **in der Mitte** ist ein Fehler.
Namen: Paket und Befehl `crapai`, Zustandsordner `.crapai/` (ADR 0017).

## 6. Fehlerbehandlung

* Der Kern wirft nur `SaraError`-Unterklassen mit **Code** (Katalog Plan Kap. 26.4, E1xx Import, E2xx Konfiguration, E3xx Anbieter, E4xx Datei, E5xx Statistik).
* An der Grenze (`cli.py`) werden Fehler abgefangen: Code → Ausgabe (`Fehler E106: … Warum … Einzelheiten … Was tun`) und **Rückgabecode**:
  0 in Ordnung, 1 Benutzerfehler, 2 Systemfehler (Datei, Sperre, Speicher, unerwartet), 4 Ergebnis mit Warnungen.
* Unerwartete Ausnahmen: Traceback in `.crapai/app.log`, dem Benutzer nur `E999` und der Klassenname (nie roher Text, der Geheimnisse enthalten könnte).
* Texte: `errors.<Code>.title|cause|action` in `en.yaml` und `de.yaml`; die Ausnahme selbst trägt eine englische, konkrete Meldung
  (Dateiname, Einstellung) für „Einzelheiten“.

## 7. Sicherheit und Datenschutz

* **Keine Geheimnisse in Dateien.** `project.yaml` enthält nur den *Namen* der Umgebungsvariable (`llm.api_key_env`); jeder andere Schlüsselname
  im Modell wird als „unbekannte Einstellung“ abgelehnt; Fehlertexte wiederholen den fehlerhaften Wert nie (`hide_input_in_errors`).
* Kein Datensatzinhalt im Log (nur IDs, Zahlen, Dateinamen).
* Lokale Pfade aus Literaturexporten (RIS `L1`/`L2`/`L4`, BibTeX `file`) werden nicht in die Auswertungsspalten übernommen (RIS: nur `extra_json`, BibTeX: verworfen).
* `sources/` wird nie verändert; `reference/` (Vorgängercode) nie importiert.

## 8. Teststrategie

| Ebene | Wo | Inhalt |
|---|---|---|
| Einheit | `tests/unit/` | je Modul; Erfolg, Fehlerfälle, Grenzwerte; `hypothesis` für Eigenschaften (verlustfreie Rundreise von `records.csv`, Idempotenz der Bereinigung) |
| Orakel | `tests/data/EXPECTED.json` | unabhängig berechnete Sollzahlen der Fixtures (z. B. Zotero-RIS 706 Datensätze / 156 Abstracts) |
| Golden | `tests/unit/test_legacy_golden.py` | Statistik gegen archivierte Berichte des Vorgängers |
| Architektur | `tests/unit/test_layering.py` | Schichtenregel |
| Randfälle | `tests/unit/test_edge_cases.py` | Schutzzweige, die nur bei Störungen laufen; Grundlage ist eine Zweigabdeckungsmessung (Stand 96 %, neuer Code 99-100 %) |
| Dokumentation | `tests/unit/test_docs.py`, `test_docstrings.py`, `test_i18n_parity.py` | Handbuch, Docstrings und Texte bleiben mit dem Code konsistent |
| Integration | `tests/integration/` | Meilenstein A: alle Fixtures über die echte CLI importieren |
| Live | Marker `live` | echte API-Aufrufe; nie in der CI, nur auf Anweisung |

Unveränderlich: `tests/data/**`, `tests/legacy_runs/**`, `tests/expected/**`, `reference/**`.

## 9. Wichtige Entscheide (ADR)

Siehe `docs/adr/`: 0001 Projektordner statt Datenbank · 0002 CSV/JSONL kanonisch, XLSX nur Export · 0003 Append-only-Checkpoint ·
0004 asyncio · 0005 strukturierte Antworten · 0006 UI und Worker getrennt · 0007 Pydantic + YAML · 0013 Streamlit · 0014 SwissGPT als Hauptanbieter · 0015 kein Volltext in v1 ·
0019 Vorfilter-Reihenfolge · 0023 Keyword-Vorfilter und Prompt-Kontext · 0024 Vergleich mehrerer Läufe (Test-Retest) ·
0025 Schiedsrichter und Diskussion zwischen Läufen.

Umsetzungsentscheide, die im Code gefallen sind (auch in `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`, Abschnitt 6):

* Schichtentest mit `ast` statt `import-linter` (keine neue Abhängigkeit).
* BibTeX: eigener toleranter Scanner statt `pybtex` (Cochrane-Dateien sind kein gültiges BibTeX; ein Codepfad).
* Duplikate: Union-Find über Schlüssel (DOI, PMID, normalisierter Titel), im Zweifel **nicht** markieren (Titeltreffer mit verschiedenen DOIs werden verworfen); der behaltene Datensatz ist der vollständigste.
* Ausschlussgründe: ein Grund je Datensatz, Besitz je Schritt, Rangfolge `NOT_SCREENABLE` > `RETRACTED` > `NO_ABSTRACT`; Duplikate ersetzen Gültigkeits- und Vorfiltergründe (ADR 0018, 0019). Reihenfolge: Import, Dedup, Vorfilter, Gültigkeit.
* Preflight: `check_project` führt Dedup, Vorfilter und Gültigkeit in der Reihenfolge Import, Dedup, Vorfilter, Gültigkeit aus (`update=True`) und urteilt danach nur über gespeicherte Markierungen; Status `ERROR` nur, wenn nichts ans Modell gehen kann, sonst `WARNING` bei Hinweisen. Die Meldungen sind i18n-Schlüssel, keine Texte.
* Ereignisse: Die Flusszahlen werden nie gespeichert, sondern bei jedem Aufruf aus `data/events.jsonl` berechnet. Import-Ereignisse zählen auf; Dedup-, Gültigkeits- und Vorfilter-Ereignisse sind **Momentaufnahmen** der ganzen Neuberechnung (das jeweils letzte gilt), damit wiederholtes `crapai dedup` nichts doppelt zählt. Kann ein Ereignis nicht geschrieben werden, bleibt die bereits erledigte Arbeit gültig (Warnung im Protokoll); die Ereignisse lassen sich durch erneutes Dedup und Prüfen wiederherstellen.
* Import-Protokoll als letzter Schritt (macht den Import atomar im Sinne der Buchführung).
* `Exit-Code 4` bei Warnungen (fehlende Abstracts, `EMPTY_RECORD`).

## 10. Geplante Erweiterungen (nicht implementiert)

* PRISMA-Flussdiagramm als Bild (PNG/SVG); die Zahlen selbst (`prisma_flow.json`) werden bereits über `crapai export --what flow`
  geschrieben.
* Vergleich der Modellentscheide mit menschlichen Entscheidungen (Plan Kap. 14, "Gegen Mensch").
* Ein Komfortbefehl, der mehrere Modelle automatisch nacheinander durchläuft (`--repeats N` aus dem Plan); heute: mehrere
  separate `crapai screen`-Aufrufe, siehe ADR 0024.
* Oberflächen-Schaltflächen, um `crapai adjudicate`/`crapai discuss` direkt zu starten (vorerst nur Befehlszeile).
* Weitere Anbieter ausser OpenAI/OpenAI-kompatibel (SwissGPT) und dem Mock.
* Volltext-Screening (ADR 0015, bewusst ausserhalb von Version 1).

Laufend aktueller Stand, nächster Schritt und Testzahl: `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`.
