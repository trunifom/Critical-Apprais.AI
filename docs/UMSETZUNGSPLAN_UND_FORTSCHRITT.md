# UMSETZUNGSPLAN_UND_FORTSCHRITT.md - Was ist fertig, was kommt als Nächstes

**Zweck:** Diese Datei ist das Übergabeprotokoll zwischen Agenten-Sitzungen. Ein Agent ohne Gedächtnis liest sie zuerst
(nach `AGENTS.md`) und weiss danach, was erledigt ist, wo der Code steht und womit er weiterarbeitet.
Die Detailbeschreibung jeder Aufgabe steht in `tasks/T-….md`; die Spezifikation in `docs/PROJEKTPLAN.md`.

**Projekt:** Critical Apprais.AI (nicht SARA). Repository: `https://github.com/trunifom/Critical-Apprais.AI.git`.
Git-Identität nur lokal im Repo: `trunidom <dominique.truninger@gmail.com>`.

## 1. Regeln für diese Datei (bitte einhalten)

1. **Nach jeder fertigen, getesteten Funktion** einen Commit machen (ausführliche Commit-Nachricht: was, warum, wie getestet),
   danach in Abschnitt 4 die Zeile abhaken: `[x]`, Datum und Uhrzeit (Ortszeit, `JJJJ-MM-TT HH:MM`) und **Kurz-Hash** des Commits.
2. Die Zeile mit Hash gehört in **denselben oder den unmittelbar folgenden Commit**. Einfachster Weg: erst Code-Commit,
   dann Hash in dieser Datei eintragen, dann kleiner Commit `docs(progress): ...`. Der Hash in der Tabelle zeigt auf den Code-Commit.
3. **Der Projektleiter pusht selbst.** Der Agent pusht nie. Der Branch-Stand auf GitHub kann daher hinter dem lokalen Stand liegen;
   massgebend ist `git log` im Arbeitsordner.
4. Wird eine Aufgabe geteilt oder ändert sich der Plan, hier die Tabelle anpassen und im Abschnitt 6 (Abweichungen) begründen.
5. Nicht geändert werden dürfen: `reference/**`, `tests/data/**`, `tests/legacy_runs/**`, `tests/expected/**`.
   Persistierte Namen (Spalten, Enum-Werte, JSON-Schlüssel, Dateinamen) sind Datenverträge.

## 2. Schnellstart für einen neuen Agenten

```powershell
Set-Location "C:\Users\trug\Documents\GitHub\Critical-Apprais.AI"
git status ; git branch --show-current ; git log --oneline -10
.\.venv\Scripts\Activate.ps1                      # falls .venv fehlt: py -3.11 -m venv .venv ; python -m pip install -e ".[dev,import,cli]"
python -m pytest -q ; python -m ruff check . ; python -m mypy src
```

Danach: erste offene Zeile in Abschnitt 4, deren Abhängigkeiten erledigt sind. Karte `tasks/<ID>.md` und die dort genannten
Plankapitel lesen (`python scripts/plan_chapter.py <Nr>`), Test zuerst, dann implementieren. **Es wird direkt auf `main` gearbeitet, ohne Task-Branches** (Entscheid des Projektleiters vom 2026-09-30: er ist allein im Projekt).
Commit-Schema: `type(scope): Zusammenfassung (Karten-ID)`; Ende der Nachricht: die Attributionszeile der Umgebung.

## 3. Stand der Umgebung

| Punkt | Stand |
|---|---|
| Branch | Nur `main`. Die frühen Task-Branches wurden fast-forward nach `main` gemergt und gelöscht. Push: `git push origin main` durch den Projektleiter |
| Tests | 1240 passed (`python -m pytest -q`) |
| Lint / Typen | `ruff` sauber (ohne `reference/`), `mypy src` sauber |
| CI | `.github/workflows/ci.yml` geschrieben (Linux/Windows/macOS x Python 3.11-3.13), noch nie auf GitHub gelaufen |
| Extras in `pyproject.toml` | `import` (rispy, pybtex, openpyxl, pymupdf, pdfplumber, pylatexenc), `cli` (typer, rich), `dev`, u. a. Neue Abhängigkeiten ausserhalb der Extras: vorher fragen |
| Technische Namen | endgültig (ADR 0017): Paket und Befehl `crapai`, Zustandsordner `.crapai/`, Umgebungsvariablen `CRAPAI_...`; Kurzform CrAp-AI |

## 4. Fortschritt (abhaken)

Legende: `[ ]` offen · `[~]` begonnen · `[x]` fertig (mit Datum, Uhrzeit, Commit-Hash) · `[-]` zurückgestellt.
Reihenfolge = empfohlene Arbeitsreihenfolge. Aufwand in Stunden (Schätzung der Karte).

### Phase A/B - Umgebung und Git

| Status | Schritt | Datum / Uhrzeit | Commit |
|---|---|---|---|
| [x] | Umgebung (.venv, 47 Tests grün) | 2026-09-30 14:4x | - |
| [x] | Git init, Remote `origin`, Erst-Commit (200 Dateien) | 2026-09-30 14:55 | `9092315` |

### M0 - Grundlagen

| Status | Karte | Inhalt | h | Datum / Uhrzeit | Commit |
|---|---|---|---|---|---|
| [x] | T-M0-02 | ruff sauber (ohne `reference/`) | 4 | 2026-09-30 14:59 | `ab687e1` |
| [x] | T-M0-02 | Layer-Test (`tests/unit/test_layering.py`, ohne import-linter) | | 2026-09-30 15:00 | `38d230a` |
| [x] | T-M0-02 | CI-Workflow `.github/workflows/ci.yml`, Kartenstatus | | 2026-09-30 15:01 | `58472eb` |
| [x] | T-M0-01 | Lizenz des Codes: PolyForm Noncommercial 1.0.0 (`LICENSE`, ADR 0016). **Offen bleiben:** Rechteinhaber klären, Fremdmaterial vor Veröffentlichung prüfen | 2 | 2026-09-30 16:52 | `c04f8c0` |
| [x] | T-M0-03 | Umbenennung: Kurzform CrAp-AI, Paket und Befehl `crapai`, Zustandsordner `.crapai/`, Umgebungsvariablen `CRAPAI_` (ADR 0017) | 3 | 2026-09-30 17:04 | `4bf0075` |

### M1 - Import steht (Meilenstein A)

| Status | Karte | Inhalt (Datei, Kernfunktion) | h | Datum / Uhrzeit | Commit |
|---|---|---|---|---|---|
| [x] | T-M1-01 | Paketskelett: `__init__.py` in `project, io, io.readers, prisma, screening, llm, prompts, stats, services`; README-Schnellstart | 4 | 2026-09-30 15:05 | `a4a1756` |
| [x] | T-M1-02 | `errors.py`: Ausnahmehierarchie `SaraError` mit Fehlercodes (Kap. 28.7, 26.4) | | 2026-09-30 15:09 | `5c22ef8` |
| [x] | T-M1-02 | `config/models.py`: Pydantic-Modelle für `project.yaml` (kein API-Schlüssel speicherbar) | 6 | 2026-09-30 15:11 | `fcfb8f7` |
| [x] | T-M1-02 | `config/loader.py`: Laden mit präzisen Fehlern (E201/E203, Pfad + Grund) | | 2026-09-30 15:12 | `2c3a108` |
| [x] | T-M1-02 | `config/loader.py`: Rangfolge CLI > env (`CRAPAI_ABSCHNITT__SCHLUESSEL`) > project.yaml > user > Standard | | 2026-09-30 15:14 | `e5403cc` |
| [x] | T-M1-03 | `project/atomic.py`: atomares Schreiben (`os.replace`, Wiederholung, Ausweichname) | 6 | 2026-09-30 15:15 | `4cacadf` |
| [x] | T-M1-03 | `project/lock.py`: Lock mit Heartbeat, Übernahme veralteter Locks | 2026-09-30 15:17 | `17d426d` | |
| [x] | T-M1-03 | `project/workspace.py`: Ordnerstruktur Kap. 6, Schema-Version | | 2026-09-30 15:17 | `54d3144` |
| [x] | T-M1-04 | `io/readers/detect.py`: Formaterkennung RIS/NBIB/BibTeX/XLSX/ZIP/PDF (Inhalt vor Endung; Typ, Konfidenz, Grund) | 4 | 2026-09-30 15:20 | `55a2f7b` |
| [x] | T-M1-04 | `io/readers/detect.py`: CSV/TSV-Erkennung mit Trennzeichen und Kodierung | | 2026-09-30 15:23 | `4020d3b` |
| [x] | T-M1-05 | `io/readers/base.py`: gemeinsame Typen `RawRecord`/`ReadResult`, Dekodierung mit Kodierungskette | | 2026-09-30 15:24 | `7738aa4` |
| [x] | T-M1-05 | `io/readers/ris.py`: RIS-Reader (Fortsetzungszeilen, L15 beheben; 706/156, 6, 46 laut EXPECTED.json) | 5 | 2026-09-30 15:27 | `a5b819d` |
| [x] | T-M1-06 | `io/readers/nbib.py`: NBIB/MEDLINE (100 und 62 Datensätze) | 4 | 2026-09-30 15:31 | `049310f` |
| [x] | T-M1-07 | `io/readers/bibtex.py`: BibTeX (48, 706; 11,5-MB-Datei nur Marker `large`) | 6 | 2026-09-30 15:39 | `ddf0afc` |
| [x] | T-M1-08 | `io/readers/tabular.py`: CSV/TSV/XLSX (Kodierung, Trennzeichen, Spaltenzuordnung) | 5 | 2026-09-30 15:43 | `bb7a7de` |
| [x] | T-M1-10 | `io/normalize.py`: `to_record`/`to_records` (RawRecord -> Record, EMPTY_RECORD, DOI, extra_json) | 5 | 2026-09-30 15:51 | `19c6399` |
| [x] | T-M1-10 | `io/records_store.py`: `Record`-Modell, `records.csv` schreiben/lesen, Backups | | 2026-09-30 15:49 | `6e223c5` |
| [x] | T-M1-10 | `io/normalize.py`: Hilfsfunktionen `clean_text`, `normalize_doi`, `coerce_year`, `normalize_list` | | 2026-09-30 15:46 | `d73e337` |
| [x] | T-M1-10 | `io/import_log.py`: SHA-256 der Quellen, Import-Log (JSONL), Wiederimport-Erkennung E106 | | 2026-09-30 15:53 | `f2fc282` |
| [x] | T-M1-11 | `io/readers/dispatch.py` + `services/importing.py`: Import-Dienst (erkennen, lesen, Quelle kopieren, normalisieren, `records.csv`, Log; Lock; E106) | 3 | 2026-09-30 15:58 | `edefbdb` |
| [x] | T-M1-11 | `services/project.py`: `create_project` aus Vorlage (`blank`, `demo`), `project_status` | | 2026-09-30 16:00 | `292650c` |
| [x] | T-M1-11 | `i18n/messages.py` + Texte `cli.*`/`errors.*` in `en.yaml` und neuer `de.yaml` | | 2026-09-30 16:03 | `a0b1e61` |
| [x] | T-M1-11 | `cli.py`: `crapai init`, `crapai import`, `crapai status` (Exit-Codes Kap. 15.1, `--json`, `--lang`) | | 2026-09-30 16:10 | `cb2fa2f` |
| [x] | T-M1-11 | `tests/integration/test_milestone_a_import.py`: Abnahmetest Meilenstein A | | 2026-09-30 16:11 | `94b21db` |
| [x] | T-M1-12 | `i18n/texts/de.yaml` + neue Schlüssel (kann jederzeit parallel; auf Wunsch des Projektleiters) | 4 | 2026-09-30 16:23 | `e1dd6e5` |
| [-] | T-M1-09 | PDF-ZIP-Reader (zurückgestellt, ADR 0015: kein Volltext in v1) | 4 | | |

**Meilenstein A ist erreicht (2026-09-30 16:11, `94b21db`).** Bedingung war: alle Fixtures aus `tests/data/` importierbar sind, die Zahlen `tests/data/EXPECTED.json` entsprechen
und `crapai init/import/status` läuft.

### Nachträge und Dokumentation (laufend)

| Status | Schritt | Datum / Uhrzeit | Commit |
|---|---|---|---|
| [x] | Fehlerbehebung: gesperrte `records.csv` (Excel) lässt den Import mit `E401` scheitern statt eine Nebendatei zu schreiben | 2026-09-30 16:30 | `42eefa3` |
| [x] | Dokumentationssatz: `docs/BENUTZERHANDBUCH.md`, `docs/ENTWICKLERDOKUMENTATION.md`, `docs/ARCHITEKTUR.md`, `README.md`, `CHANGELOG.md`, Doku-Konsistenztest `tests/unit/test_docs.py` | 2026-09-30 16:34 | `d25f329` |

**Pflicht bei jeder Aufgabe:** die fünf Dokumente mitführen (neue Befehle/Optionen ins Benutzerhandbuch, neue Schnittstellen und Datenformate in die Entwicklerdokumentation,
neue Module in die Architektur, Änderungen ins `CHANGELOG.md`, Stand ins `README.md`). `tests/unit/test_docs.py` schlägt fehl, wenn Handbuch, Code und Spalten auseinanderlaufen.

### M2 - Aufbereitung (Meilenstein A ist erreicht)

| Status | Karte | Inhalt | h | Datum / Uhrzeit | Commit |
|---|---|---|---|---|---|
| [x] | T-M2-01 | `prisma/dedup.py`: Duplikate nicht löschend markieren (4 Strategien, normalisierte Titel, vollständigster Datensatz behalten) | 6 | 2026-09-30 17:10 | `edc0d2f` |
| [x] | T-M2-01 | `services/dedup.py`, `crapai dedup`, Texte, Dokumentation (Folge-Commit; `edc0d2f` liess den Doku-Wächtertest kurz rot) | | 2026-09-30 17:16 | `97bf716` |
| [x] | T-M2-03 | `prisma/validity.py`, `prisma/reasons.py`, `services/validity.py`: `NO_ABSTRACT`, `NOT_SCREENABLE`, `RETRACTED`, `abstract_quality`; ADR 0018. Ein Abnahmekriterium (Cochrane-Beispiel als `suspect_concat`) ist ohne Wörterbuch nicht erfüllbar | 3 | 2026-09-30 18:05 | `5034089` |
| [x] | T-M2-04 | `services/preflight.py` (`check_file`, `check_project`, Codes `ProjectIssue`), `crapai check` (Rückgabecode 0/4/1, `--read-only`, `--json`); Fehlerbehebung: fehlende Datei in `detect_format` jetzt `E101` | 4 | 2026-09-30 18:28 | `8171cc2` |
| [x] | T-M2-05 | `cost/tokenizers.py`, `cost/pricing.py`, `cost/estimator.py` neu geschrieben (echte Texte, Kostenband, Worst Case), `services/cost.py`, `pricing.csv` | 6 | 2026-09-30 18:58 | `4218e74` |
| [x] | T-M2-07 | `prisma/events.py`, `prisma/flow.py`, `services/events.py`: Ereignisse in `data/events.jsonl`, Flusszahlen daraus abgeleitet, Orakeltest gegen den Vorgänger (beide Berichtsmodi) | 5 | 2026-09-30 19:08 | `c170335` |
| [x] | T-M2-08 | `prisma/prefilters.py`, `services/prefilter.py`, neue Gründe `PREFILTER_*`, ADR 0019; `crapai check` ruft sie zwischen Dedup und Gültigkeit auf | 5 | 2026-09-30 19:19 | `98c4576` |
| [x] | T-M2-06 | `cost/duration.py` (Dauer, Bestätigungsregel), Kosten-, Token- und Dauerausgabe in `crapai check` | 4 | 2026-09-30 19:24 | `c0a0fba` |
| [ ] | T-M2-02 | optionale unscharfe Duplikatsuche mit Prüfliste (`rapidfuzz` ist im Extra noch nicht enthalten: vorher fragen) | 4 | | |

### Prüfung "alles dokumentiert, committet, getestet?" (Sitzung vom 2026-09-30)

| Status | Schritt | Datum / Uhrzeit | Commit |
|---|---|---|---|
| [x] | Abdeckungsmessung (93 % → 96 %), 37 Randfall-Tests, Wächtertest für Docstrings/Rückgabetypen (`test_edge_cases.py`, `test_docstrings.py`) | 2026-09-30 17:30 | `523de8b` |
| [x] | Tests für die übernommenen Module `criteria/template` und `legacy` (`test_ported_modules.py`) | 2026-09-30 17:31 | `71a314d` |
| [x] | **CI-Fehler gefunden und behoben:** alle 9 Testjobs auf GitHub rot; Ursache Typer-Farbcodes bei gesetztem `GITHUB_ACTIONS`; `tests/conftest.py`, Regressionstest, `-ra --tb=short` | 2026-09-30 17:48 | `7559f08` |
| [x] | `import.mappings` in der `project.yaml` (wiederholbarer Tabellenimport) | 2026-09-30 17:55 | `300d6fa` |

**Grenzen der Prüfung (ehrlich):** Vier frühere Commits (Fortschrittsmarken, zwischen 5 und 34 Wörter Nachricht) sind kürzer, als du es willst; sie sind bereits veröffentlicht und werden nicht umgeschrieben. `cost/estimator.py` (63 % Abdeckung) wird mit T-M2-05 neu geschrieben und dann getestet. `pytest-cov` ist nur lokal installiert (Freigabe für das Extra `dev` offen).

### M3 (Karten in `tasks/`)

| Status | Karte | Inhalt | h | Datum / Uhrzeit | Commit |
|---|---|---|---|---|---|
| [x] | T-M3-01 | `llm/base.py`, `llm/mock_provider.py`: Protokoll, Fehlerklassen mit Wiederholungsregel, Szenarien S1-S15 | 8 | 2026-10-01 | `50d26313` |
| [x] | T-M3-02 | `llm/openai_provider.py`: OpenAI und OpenAI-kompatibel (SwissGPT), Fehlerabbildung, Test mit gefälschtem Transport | 8 | 2026-10-01 | `50d26313` |
| [x] | T-M3-03 | `llm/resilience.py`: `RetryPolicy`, `call_with_retry`, `CircuitBreaker` | 6 | 2026-10-01 | `50d26313` |
| [x] | T-M3-04 | `llm/resilience.py`: `RateLimiter` (RPM/TPM), `AdaptiveConcurrency` | 8 | 2026-10-01 | `50d26313` |
| [x] | T-M3-05 | `prompts/builder.py`, Varianten, Prompt-Hash; Kostenschätzung zählt den echten Prompt | 6 | 2026-10-01 | `50d26313`, Folgecommit |
| [x] | T-M3-06 | `screening/answer.py`: Schema, Gegenprobe, Zitate, altes Format | 8 | 2026-10-01 | `50d26313` |
| [x] | T-M3-07 | `screening/engine.py`: Päckchen, Arbeiter, einziger Schreiber, Kostenlimit, Steuerdatei | 12 | 2026-10-01 | `50d26313` |
| [x] | T-M3-08 | `screening/store.py`, `services/screening.py`: Manifest, Fortsetzen, Fingerabdruck (E204), Sperre; kumulative Zähler | 8 | 2026-10-01 | `50d26313`, `7e625209` |
| [x] | T-M3-09 | `crapai screen/runs/pause/stop`, Fortschrittsbalken; Seite „Lauf“ der Oberfläche | 4 | 2026-10-01 | `20d2e8fd`, `7e625209` |
| [x] | T-M3-10 | `tests/integration/test_acceptance.py`: AT2-AT4; Live-Test ohne Schlüssel übersprungen | 4 | 2026-10-01 | `50d26313` |

**Live-Test mit echtem Schlüssel: offen.** Der Schlüssel (SwissGPT und/oder OpenAI) wird von der Projektleitung später geliefert; er wird nie in Dateien, Protokollen oder im Chat abgelegt. Ablauf: Umgebungsvariable setzen, `CRAPAI_LIVE_KEY_ENV` auf deren Namen setzen, `pytest -m live`.


## 5. Nächster Schritt (bitte aktuell halten)

**Meilenstein A ist erreicht und M1 ist vollständig** (T-M1-09 bleibt zurückgestellt). M2: `T-M2-01` (Duplikate), `T-M2-03` (Gültigkeit) , `T-M2-04` (Preflight, `crapai check`) und `T-M2-05` (Kostenschätzung), `T-M2-07` (PRISMA-Ereignisse) und `T-M2-08` (Vorfilter) und `T-M2-06` (Dauer, Kostenausgabe) sind fertig; **Meilenstein M2 ist vollständig bis auf das zurückgestellte `T-M2-02`**. **Meilenstein M3 (Screening-Kern) ist umgesetzt** (Anbieter, Wiederholung, Limiter, Prompt, Antwortprüfung, Engine mit Päckchen und Fortsetzen, `crapai screen`, Seite „Lauf“, Akzeptanztests AT2-AT4, ADR 0022). **Nächste Schritte:** Live-Test mit echtem Schlüssel (Schlüssel folgt von der Projektleitung), danach M4 (Ergebnistabelle, Test-Retest, Vergleich mit Menschen). **Zurückgestellt, nicht vergessen:** `T-M2-02` unscharfe Duplikatsuche (braucht `rapidfuzz`). Pflege der Dokumentation: Benutzerhandbuch, Entwicklerdokumentation, Architektur, README, CHANGELOG nach jeder Aufgabe mitführen.
**Erledigt (2026-10-01/02, Wunsch der Projektleitung):** alle Zusatzfunktionen sind fertig (siehe Abschnitt "Zusatzfunktionen"): Stichwort-Filter, die Vergleichsschicht für Mehrfachbewertung/Modellvergleich (`crapai compare-runs`, Dashboard-Abschnitt „Läufe vergleichen“) und das Klären von Uneinigkeit (`crapai adjudicate`, `crapai discuss`).

## 6. Abweichungen und offene Punkte

| Datum | Punkt |
|---|---|
| 2026-09-30 | Layer-Vertrag als `ast`-Test statt `import-linter` (neue Abhängigkeit, hätte Rückfrage gebraucht). Bei Bedarf später ersetzen |
| 2026-09-30 | `ruff` schliesst `reference/` aus; portierte Dateien behalten begrenzte Ignore-Regeln (`pyproject.toml`) |
| 2026-09-30 | Remote-Besitzer heisst `trunifom`, GitHub-Benutzer des Projektleiters `trunidom`; Push macht der Projektleiter |
| offen | **CI:** alle Testjobs waren rot (Ursache: von Typer erzwungene Farbcodes in `--help`), behoben in `7559f08`. Ergebnis nach dem nächsten Push prüfen (GitHub-Seite oder `curl https://api.github.com/repos/trunifom/Critical-Apprais.AI/actions/runs`); macOS und Python 3.13 sind lokal nie gelaufen |
| offen | Fehlerkatalog (Kap. 26.4) hat keinen Code für "Ordner schon initialisiert / nicht leer"; `Workspace.create` nutzt E404 mit eigener Meldung. Projektleiter soll entscheiden, ob ein neuer Code aufgenommen wird |
| 2026-09-30 | BibTeX-Reader ohne `pybtex` (eigener toleranter Scanner, ein Codepfad für gültige und ungültige Dateien); `pybtex` bleibt im Extra `import`. CI installiert jetzt `.[dev,import]` (pylatexenc) |
| 2026-09-30 | Exit-Code 4 (Warnungen) bei `crapai import`, wenn keine oder wenig (< 60 %) Abstracts vorhanden sind oder `EMPTY_RECORD` entstehen. Die Fixtures `example_db_nr1-3` haben keine Abstracts, deshalb liefert der Abnahmefall der Karte T-M1-11 Exit-Code 4 |
| erledigt | `import.mappings` (Kap. 25.5) ist im Modell und wird beim Import gelesen; das Programm schreibt die `project.yaml` nicht selbst (Kommentare bleiben). Siehe Abschnitt "Nachträge" |
| **zurückgestellt, nicht vergessen** | **Unscharfe Duplikatsuche (T-M2-02):** braucht `rapidfuzz` (neue Abhängigkeit, Freigabe der Projektleitung nötig) und die Prüfliste `reports/possible_duplicates.csv` (Treffer als `POSSIBLE_DUPLICATE`, nie automatisch ausgeschlossen); `dedup_method` = `fuzzy`; Schwelle einstellbar (`dedup.fuzzy.threshold`, im Modell schon vorhanden). Die Strategien-Schnittstelle in `prisma/dedup.py` ist dafür vorbereitet |
| offen | Rechteinhaber in der Zeile `Required Notice` (LICENSE) mit der Hochschule klären; Fremdmaterial (Literatur, Berichte, ZIP) vor einer öffentlichen Veröffentlichung prüfen oder ausschliessen (ADR 0016) |

## Gesamtprüfung und Überarbeitung (2026-10-01)

Auf Wunsch der Projektleitung wurde der gesamte Code von drei unabhängigen Prüfern gelesen (Import und Reader; Projektordner, Fehlerbehandlung, Protokolle; PRISMA, Kosten, Werkzeuge).
Alle bestätigten Fehler sind behoben und mit Tests abgesichert; die Entscheide stehen in `docs/adr/0020-ergebnisse-der-gesamtpruefung.md`, die Einzelheiten im CHANGELOG.

| Erledigt | Was | Commit |
|---|---|---|
| [x] | Sperre, anhängende Dateien, atomares Schreiben | `3f87d80` |
| [x] | Befehlszeile, Ereignisse, PRISMA-Fluss, Kosten, Konfiguration, `crapai unlock` | `62822ae` |
| [x] | Import, Reader, Dedup, Vorfilter, Validität, Kriterien | `f8ea645` |
| [x] | `crapai export` (CSV, XLSX, RIS, PRISMA-Fluss), Formatierung, CI, Dokumentation | siehe `git log` |

Offen aus der Prüfung (bewusst nicht geändert, siehe ADR 0020): ungenutzte Aufzählungen in `enums.py`; `tiktoken` wird in der CI nicht installiert.

## Zusatzfunktionen auf Wunsch der Projektleitung (2026-10-01)

Zwei Funktionen ausserhalb der Aufgabenkarten, auf Wunsch der Projektleitung im Chat; Rückfrage per `AskUserQuestion` geklärt: Stichwort-Filter als **beides** (harter Vorfilter und optionaler Prompt-Kontext, unabhängig zuschaltbar), Mehrfachbewertung als **mehrere separate `crapai screen`-Aufrufe** plus neue Vergleichsschicht.

| Status | Schritt | Datum / Uhrzeit | Commit |
|---|---|---|---|
| [x] | Stichwort-Vorfilter `prefilters.keywords` (neuer Grund `PREFILTER_KEYWORD`) und `screening.include_keywords_in_prompt` (Prompt-Kontext, ändert den Prompt-Hash nicht, geht aber in den Lauf-Fingerabdruck ein); ADR 0023 | 2026-10-01 | `cfd1929f` |
| [x] | Mehrfachbewertung/Modellvergleich: Vergleichsschicht `stats/agreement.py` (Cohen's/Fleiss' Kappa, Landis & Koch, instabile Datensätze), `services.results.compare_runs`/`export_comparison`, Befehl `crapai compare-runs`, Dashboard-Abschnitt „Läufe vergleichen“ (Farbe je Lauf); ADR 0024 | 2026-10-01 | `b83766c2` |
| [x] | Uneinigkeit klären: `crapai adjudicate` (Schiedsrichter-Modell, aktuelle `llm:`-Einstellungen), `crapai discuss` (Original-Modelle jedes Laufs diskutieren, bis zu `discussion.max_rounds` Runden, dann Mehrheit/`NO_CONSENSUS`); `prompts/resolution.py`, `services/resolution.py`, gespeichert wie ein gewöhnlicher Lauf (`kind` `adjudicate`/`discuss`); ADR 0025 | 2026-10-02 | `5fb3742d` |
| [x] | Durchsicht auf Wunsch der Projektleitung: Fehlerbehandlung, Protokolle, Kommentare, Hilfetexte, Dokumentation für Stichwort-Filter/Lauf-Vergleich/Schiedsrichter-Diskussion; 6 echte Lücken behoben (Validierungsreihenfolge, doppelte Lauf-IDs, verschluckte `max_rounds=0`/leeres `tie_break`, reihenfolgeabhängiges `--resume`, stillschweigend "erledigt" bei beschädigtem Plan, unübersetzter `typer.BadParameter`); Protokollierung in `services/resolution.py` ergänzt; ADR 0025 Nachtrag | 2026-10-02 | `c763d16c` |

## Oberfläche, Protokoll-System und Arbeitsablauf (2026-10-01)

| Erledigt | Was | Commit |
|---|---|---|
| [x] | Lokale Streamlit-Oberfläche (`crapai ui`), neun Seiten, getestet mit `AppTest` | `bfccaa5` |
| [x] | `logging_setup.py` (Sitzungskennung, Schutz vor Schlüsseln, `--verbose`), `ErrorReport` | `bfccaa5` |
| [x] | `scripts/qa.py`, schnellere und von der Maschine unabhängige Tests, CI mit Extra `ui` | `bfccaa5` |

Nicht Teil dieser Version (bewusst): Kriterien-Editor nach Rahmenwerk (bearbeitet wird vorerst `project.yaml` direkt), PRISMA-Grafik (PNG/SVG, Export M8).

## Zweite Gesamtprüfung auf Wunsch der Projektleitung (2026-10-01)

Erneute Durchsicht des gesamten Codes (Ablauf, Architektur, Prozesse, Funktionen, Import/Export, Datenstrukturen, Fehlerbehandlung/Protokolle, Dokumentation, Oberfläche); sieben unabhängige Prüfer, danach Behebung mit Tests.

| Status | Schritt | Datum / Uhrzeit | Commit |
|---|---|---|---|
| [x] | Sperre (Race in `acquire()`, stille Alternativdatei in `heartbeat()`), Oberfläche (Preistabellen-Lesefehler, Try/Except aus Seitencode entfernt), `resolution.py` (verwaistes `asyncio.gather`-Teilziel), `engine.py` (übersprungene Prüfung bei Teil-Päckchen, überschriebener Stop-Grund), Reader (stiller Jahr/Datum-Verlust), Prompt-Injection-Schutz (Unicode-Ausweichzeichen statt HTML-Entities) in `prompts/builder.py`/`prompts/resolution.py`; JSON-Gleichstand `adjudicate`/`discuss` mit `screen`; Farbkontrast `RUN_COLORS` (hell); `README.md`/`ARCHITEKTUR.md`/`BENUTZERHANDBUCH.md` auf den tatsächlichen Stand gebracht | 2026-10-01 | `b11de723` |

Bewusst nicht geändert: `SYSTEM_ERROR_CODES` in `cli.py` (E404/E405 sehen wie eine Lücke aus, aber 9 bestehende Tests verlangen ausdrücklich Rückgabecode 1 dafür; Kommentar statt Änderung). Zurückgestellt: Kosten-/Dauerschätzung vor `crapai adjudicate`/`crapai discuss` (zeigt bisher nur die Anzahl umstrittener Datensätze) - bei `discuss` mit mehreren Läufen, Modellen und Preisen wäre eine schnelle Schätzung eher still falsch als einfach fehlend. Weitere, kleinere Funde (u. a. `enums.py`-Drift, RIS-Feinheiten, XLSX-Randfall, Fuzzy-Logik in `prisma/events.py`/`dedup.py`) sind notiert, aber nicht Teil dieser Runde.

## Volltext-Screening mit PDF-Dokumenten (ADR 0026, hebt ADR 0015 auf; 2026-10-02)

Auftrag der Projektleitung im Chat: Volltext-Screening umsetzen (bisher auf Meilenstein M7 vertagt), ausserdem Speichern/Laden wiederverwendbarer Settings-Profile und drei zusätzliche Export-Formate (BibTeX/NBIB, PRISMA-Fluss als PNG/SVG, DOCX-Bericht). Reihenfolge laut Rückfrage: zuerst Volltext-Screening. Plan: `docs/adr/0026-volltext-screening.md`, Kapitel 8.9/25.6/29.8.

| Status | Schritt | Datum / Uhrzeit | Commit |
|---|---|---|---|
| [x] | ADR 0026, `project.mode: fulltext` zugelassen, `PromptBuilder.build_fulltext()` (die vorbereiteten Varianten `baseline_fulltext`/`gpt_improved_fulltext` erstmals nutzbar) | 2026-10-02 | `b0cacdcef` |
| [x] | `io/readers/pdf_zip.py` (T-M1-09 fertig umgesetzt statt zurückgestellt): ZIP nie entpackt, PyMuPDF→pdfplumber, Qualitätskennzahlen, `NO_TEXT`/`ENCRYPTED`/`IMPORT_ERROR`; `io/fulltext_link.py`: Zuordnung per DOI/Titel zu bestehendem Datensatz (neue, zusätzliche Zeile mit `fulltext_of`), kein Treffer → `reports/unmatched_pdfs.csv`, nie verworfen | 2026-10-02 | `cb8d0c2cd` |
| [x] | `prompts/fulltext_sections.py` (Abschnitts-Erkennung), `screening/fulltext.py` (Strategien `truncate`/`sections` als reine Funktionen; `map_reduce` nur als Textaufteilung vorbereitet) | 2026-10-02 | `f6df60764` |
| [x] | Engine-Anbindung: `PlanItem.fulltext`, `eligible_records()` plant im Volltext-Modus nur Anker-Datensätze mit brauchbarem PDF-Anhang, `--resume` liest die PDF erneut aus dem Zip, `screen_project()` lehnt `strategy: map_reduce` beim Start klar ab (E203), PRISMA-Ereignis `SCREEN_FT` statt `SCREEN_TA`; neue Variante `structured_fulltext` (JSON statt Legacy-XXX/YYY) | 2026-10-02 | `2ea147f2c` |

| [x] | Kostenvoranschlag berücksichtigt im Volltext-Modus die tatsächliche (zugeschnittene) PDF-Länge, lehnt `map_reduce` wie `crapai screen` ab; Oberfläche: ZIP-Hochladen (Vorschau über `check_fulltext_zip`), Moduswahl samt `prompt_variant`/`output_format`/`fulltext.strategy` im Einstellungsformular | 2026-10-02 | `21efd0baf` |

Noch offen (nicht Teil dieser Runde, bewusst zurückgestellt): `map_reduce`-Strategie in der Engine (bisher nur abgelehnt, nicht umgesetzt); Einzel-PDF-Import ohne Zip; OCR für gescannte PDFs.

## Wiederverwendbare Settings-Profile (ADR 0027, 2026-10-02)

Zweiter Teil des Auftrags (nach Volltext-Screening). Kein Plankapitel dafür vorhanden; Entwurf lehnt sich an die bestehende Überschreibdatei (ADR 0021) an.

| Status | Schritt | Datum / Uhrzeit | Commit |
|---|---|---|---|
| [x] | `config/profiles.py` (`SettingsProfile`, speichert `objectives`/`criteria`/`screening`/`llm` aus der wirksamen Konfiguration, lädt in `project.overrides.yaml`, nie in `project.yaml`), Befehle `crapai profile save/load/list/show/delete`, Oberfläche (Einstellungen-Seite) | 2026-10-02 | `e8d57bd7f` |

## Drei zusätzliche Export-Formate (ADR 0028, 2026-10-02)

Dritter und letzter Teil des Auftrags. Kein Plankapitel dafür vorhanden.

| Status | Schritt | Datum / Uhrzeit | Commit |
|---|---|---|---|
| [x] | `io/writers/bibtex.py`, `io/writers/nbib.py` (symmetrisch zu den Lesern; NBIB bewusst ohne Screening-Vermerke, kein passendes Feld); `io/writers/prisma_image.py` (PRISMA-2020-Diagramm als PNG/SVG, reines `matplotlib` ohne `pyplot`); `crapai export --format bibtex/nbib`, `--what flow --format png/svg` | 2026-10-02 | `35d0c00a8` |
| [x] | `io/writers/docx_report.py` (Ziele, Kriterien, PRISMA-Fluss, Ergebnisse des neusten Laufs); neue Abhängigkeit `python-docx` (Extra `report`, von der Projektleitung freigegeben); `crapai export --what report`; Oberfläche: Formatauswahl jetzt auch für `flow` (vorher fehlte sie dort); CI installiert neu `stats`/`report` | 2026-10-02 | `b1e764c1d` |

Damit sind alle drei Teile des Auftrags (Volltext-Screening, Settings-Profile, Export-Formate) umgesetzt. Offen bleiben die an den jeweiligen Stellen dokumentierten, bewusst zurückgestellten Punkte (u. a. `map_reduce`-Strategie in der Engine, Vergleich mit menschlichen Entscheidungen, PRISMA-Bild im DOCX-Bericht einbetten).

## Dokumentations-Nachbesserung und Ende-zu-Ende-Prüfung des Volltext-Pfads (2026-10-02)

Auftrag der Projektleitung: GUI-Texte/Hinweise nach den drei vorangehenden Erweiterungen nochmals umfassend nachführen, und den Ablauf (PDFs → Analyse → Ein-/Ausschluss → Export) Schritt für Schritt am echten Programm (nicht nur an den bestehenden Tests) nachvollziehen.

| Status | Schritt | Datum / Uhrzeit | Commit |
|---|---|---|---|
| [x] | Einleitungstexte der Seiten Daten/Export/Einstellungen/Lauf (DE+EN) um die drei neuen Funktionen ergänzt; Lauf-Seite zeigt bei Volltext-Läufen jetzt `strategy` und sperrt den Start bei `map_reduce` (war im ursprünglichen Plan vorgesehen, aber nie umgesetzt) | 2026-10-02 | `3f9c6c5ba` |
| [x] | Echter Ende-zu-Ende-Lauf von Hand (eigenes Projekt, `mine.ris` mit echten Abstracts, selbstgebautes PDF-Zip): Abstract-Screening → PDF-Zip-Import → Moduswechsel → Volltext-Screening scheiterte zunächst zweimal (`E102`, kein Datensatz übrig); dabei drei echte, von der bestehenden Testsuite nicht erfasste Fehler gefunden und behoben: (1) `prisma/dedup.py` markierte einen PDF-Anhang (`fulltext_of` gesetzt) als Duplikat seines eigenen Ankers, weil er dieselbe DOI/denselben Titel trägt; (2) `prisma/validity.py` markierte denselben Anhang `NO_ABSTRACT` (er hat naturgemäss keinen), was seinen Anker dauerhaft "nicht screenbar" machte; (3) `services/export.py` exportierte den Anhang als eigenen, unsinnigen Eintrag in BibTeX/NBIB/RIS. Jede Behebung mit Regressionstest, jeder Test nachweislich rot ohne die jeweilige Behebung (`git stash` der einen Datei, Testlauf, Wiederherstellung). Danach lief derselbe Ende-zu-Ende-Fall vollständig durch: Volltext-Screening (1 Anker geplant, Volltext tatsächlich gesendet), alle Export-Formate (CSV/XLSX/RIS/BibTeX/NBIB, PRISMA-Fluss JSON/PNG/SVG, DOCX-Bericht) | 2026-10-02 | `91a6bbf8d` |

Gesamte Suite (2000 bestanden, 2 übersprungen), `ruff check .` und `mypy src` nach beiden Commits sauber.
