# ARCHITEKTUR.md - Aufbau und Software-Architektur von Critical Apprais.AI

Stand: 2026-09-30, Version 0.0.1 (Meilenstein A: Import ist umgesetzt, Screening ist **geplant**).
Zielgruppe: Entwickler:innen und Prüfende, die verstehen wollen, wie das Programm gebaut ist und warum.
Die vollständige Spezifikation ist `docs/PROJEKTPLAN.md`; diese Datei beschreibt den **tatsächlichen Stand des Codes**
und kennzeichnet Geplantes ausdrücklich. Bedienung: `docs/BENUTZERHANDBUCH.md`. Programmierung: `docs/ENTWICKLERDOKUMENTATION.md`.

## 1. Leitgedanken

| Grundsatz | Bedeutung im Code |
|---|---|
| **Der Projektordner ist die Datenbank** | Keine Datenbank, kein Server, keine Konten. Alles liegt in Dateien (CSV, JSONL, YAML). ADR 0001 |
| **Lokal** | Nach aussen geht nur der Aufruf an den Modellanbieter (Screening, geplant). Keine Telemetrie |
| **Nichts still verlieren** | Duplikate und Datensätze ohne Abstract werden *markiert*, nie gelöscht. Unbekannte Felder wandern in `extra_json` |
| **Nie ein Label aus einer unbrauchbaren Antwort** | Fehlerhafte Modellantworten erhalten einen Status (`parse_error` u. a.), nie `INCLUDE` (geplant, Lehre L4) |
| **Alles über `study_uid`** | Jeder Datensatz bekommt beim Import eine stabile ID; nie Zeilenpositionen als Schlüssel (Lehre L1) |
| **Persistierte Namen sind Verträge** | Spaltennamen, Enum-Werte, JSON-Schlüssel, Dateinamen ändern sich nur mit Versionssprung und Migration |
| **Vorschläge, keine Entscheidungen** | Die Software ersetzt keine menschliche Prüfung |

## 2. Schichten

```
Bedienung        cli.py (typer)                      [geplant: ui/ (Streamlit)]
                    │  ruft
Dienste          services/importing.py   services/project.py   services/dedup.py   services/validity.py   services/preflight.py   services/cost.py   services/events.py   services/prefilter.py   services/export.py
                 [geplant: screening, export, evaluation]
                    │  ruft
Fachkern         io/ (readers, normalize, records_store, import_log)
                 config/ (Modelle, Loader)   project/ (Workspace, Lock, atomares Schreiben)
                 i18n/ (Texte, Meldungen)    errors.py   criteria/  cost/  enums.py  legacy.py
                 prisma/ (dedup)            [geplant: prisma/ Rest, screening/, llm/, prompts/, stats/]
                    │  spricht mit der Aussenwelt nur über
Ports/Adapter    [geplant: LLMProvider, FileStore, Clock, SecretStore, EventSink]
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
| `prisma.prefilters` | deterministische Vorfilter vor dem Modell: Sprache (ISO 639-2), Jahr, Publikationstyp; fehlende Angaben nach `on_missing` | `mark_prefilters`, `PrefilterConfig`, `normalize_language` |
| `services.prefilter` | Vorfilter aus `project.yaml` im Projekt anwenden, Ereignis schreiben | `prefilter_project` |
| `prisma.validity` | Gültigkeit: fehlende Abstracts, Front-Matter, zurückgezogene Studien, Abstract-Qualität | `mark_validity`, `ValidityConfig`, `classify_abstract`, `is_not_screenable` |
| `services.validity` | Gültigkeit im Projekt anwenden | `validate_project` |
| `cost.tokenizers` | lokale Token-Zähler: `tiktoken` (OpenAI, genau) oder Zeichenzähler mit Sicherheitszuschlag; jeder Zähler meldet `name` und `exact` | `tokenizer_for`, `CharTokenizer`, `TiktokenTokenizer` |
| `cost.pricing` | Preisquellen: editierbare `pricing.csv` (Preis je 1000 Token, Datum, Quelle) oder statisch; unbekanntes Modell = kein Preis | `CsvPriceSource`, `StaticPriceSource`, `Price` |
| `cost.estimator` | Schätzung eines Laufs aus den **echten** Texten (Titel + Abstract je Datensatz, gemeinsamer Anteil einmal gezählt), Kostenband und Worst Case; ohne I/O | `estimate_run`, `RunEstimate`, `build_shared_payload` |
| `cost.duration` | Dauerschätzung aus rpm, tpm und Parallelität; Bestätigungsregel vor einem Lauf (`--yes` oder Terminal) | `estimate_duration`, `decide_confirmation` |
| `io.writers.tables`, `io.writers.ris` | Export-Dateien: CSV (UTF-8 mit BOM, Formelschutz), XLSX (fixierte Kopfzeile, Steuerzeichen entfernt), RIS (für Literaturverwaltung); alle atomar geschrieben | `write_csv`, `write_xlsx`, `write_ris` |
| `services.export` | Datensätze (Umfang alle/screenable/excluded) und PRISMA-Fluss exportieren, ohne das Projekt zu ändern; gesperrte Zieldatei ergibt eine Ersatzdatei | `export_records`, `export_flow`, `ExportSummary` |
| `services.cost` | Schätzung für ein Projekt: zählt die Datensätze ohne Ausschlussgrund, liest `pricing.csv` des Projekts, vergleicht den Worst Case mit `limits.max_cost`; schreibt nichts | `estimate_project`, `ProjectEstimate` |
| `services.preflight` | Vorprüfung: eine Datei vor dem Import, das Projekt vor dem Lauf | `check_file`, `check_project`, `PreflightFileResult`, `ProjectReport`, `ProjectIssue` |
| `prisma.dedup` | Duplikate markieren (nicht löschend) | `mark_duplicates`, `DedupConfig`, `DedupResult`, `normalize_title`; Strategien `doi_or_title`, `strict_ids`, `title`, `title_authors` |
| `services.dedup` | Duplikate im Projekt markieren | `dedup_project` (Sperre, Sicherung, atomares Schreiben) |
| `io.readers.detect` | Formaterkennung | `detect_format` (Inhalt vor Endung), `SourceFormat` |
| `io.readers.ris` / `nbib` / `bibtex` / `tabular` | Reader | liefern `ReadResult` mit `RawRecord`-Objekten |
| `io.readers.base` | gemeinsame Typen | `RawRecord`, `ReadResult`, `decode_text` (Kodierungskette) |
| `io.readers.dispatch` | ein Einstieg | `read_source` |
| `io.normalize` | Bereinigung | `clean_text`, `normalize_doi`, `coerce_year`, `normalize_list`, `to_record(s)` |
| `io.records_store` | `records.csv` | `Record` (40 Spalten), `write_records`, `read_records`, Sicherungen |
| `io.import_log` | Import-Protokoll | SHA-256, `ImportLogEntry`, `ensure_not_imported` (E106) |
| `services.importing` | Import ablaufen lassen | `import_source` |
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
├─ runs/                       [geplant] ein Ordner je Screening-Lauf
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
0004 asyncio · 0005 strukturierte Antworten · 0006 UI und Worker getrennt · 0007 Pydantic + YAML · 0013 Streamlit · 0014 SwissGPT als Hauptanbieter · 0015 kein Volltext in v1.

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

Deduplizierung und Vorfilter (M2), Provider-Schicht mit `MockProvider`, SwissGPT/OpenAI, Ratenbegrenzer, Prompt-Bau, Antwortschema mit Prüfung,
Screening-Engine mit Checkpoint und Wiederaufnahme (M3), Ausgabe/Excel/PRISMA-Grafik, Statistik, Streamlit-Oberfläche, weitere Anbieter (M4-M8).
Reihenfolge und Stand: `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`.
