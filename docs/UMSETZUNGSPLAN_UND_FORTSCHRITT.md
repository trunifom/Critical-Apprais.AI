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
.\.venv\Scripts\Activate.ps1                      # falls .venv fehlt: py -3.11 -m venv .venv ; python -m pip install -e ".[dev]"
python -m pytest -q ; python -m ruff check . ; python -m mypy src
```

Danach: erste offene Zeile in Abschnitt 4, deren Abhängigkeiten erledigt sind. Karte `tasks/<ID>.md` und die dort genannten
Plankapitel lesen (`python scripts/plan_chapter.py <Nr>`), Test zuerst, dann implementieren. **Es wird direkt auf `main` gearbeitet, ohne Task-Branches** (Entscheid des Projektleiters vom 2026-09-30: er ist allein im Projekt).
Commit-Schema: `type(scope): Zusammenfassung (Karten-ID)`; Ende der Nachricht: die Attributionszeile der Umgebung.

## 3. Stand der Umgebung

| Punkt | Stand |
|---|---|
| Branch | Nur `main`. Die frühen Task-Branches wurden fast-forward nach `main` gemergt und gelöscht. Push: `git push origin main` durch den Projektleiter |
| Tests | 222 passed (`python -m pytest -q`) |
| Lint / Typen | `ruff` sauber (ohne `reference/`), `mypy src` sauber |
| CI | `.github/workflows/ci.yml` geschrieben (Linux/Windows/macOS x Python 3.11-3.13), noch nie auf GitHub gelaufen |
| Extras in `pyproject.toml` | `import` (rispy, pybtex, openpyxl, pymupdf, pdfplumber, pylatexenc), `cli` (typer, rich), `dev`, u. a. Neue Abhängigkeiten ausserhalb der Extras: vorher fragen |
| Technische Namen | vorläufig `saralocal` / `sara` / `.sara/` (Umbenennung = T-M0-03, nur auf Anweisung) |

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
| [ ] | T-M0-01 | Rest: Lizenz des Codes, Ablage (nur nach Entscheid des Projektleiters) | 2 | | |
| [ ] | T-M0-03 | Umbenennung technischer Namen (nur nach Entscheid des Projektleiters) | 3 | | |

### M1 - Import steht (Meilenstein A)

| Status | Karte | Inhalt (Datei, Kernfunktion) | h | Datum / Uhrzeit | Commit |
|---|---|---|---|---|---|
| [x] | T-M1-01 | Paketskelett: `__init__.py` in `project, io, io.readers, prisma, screening, llm, prompts, stats, services`; README-Schnellstart | 4 | 2026-09-30 15:05 | `a4a1756` |
| [x] | T-M1-02 | `errors.py`: Ausnahmehierarchie `SaraError` mit Fehlercodes (Kap. 28.7, 26.4) | | 2026-09-30 15:09 | `5c22ef8` |
| [x] | T-M1-02 | `config/models.py`: Pydantic-Modelle für `project.yaml` (kein API-Schlüssel speicherbar) | 6 | 2026-09-30 15:11 | `fcfb8f7` |
| [x] | T-M1-02 | `config/loader.py`: Laden mit präzisen Fehlern (E201/E203, Pfad + Grund) | | 2026-09-30 15:12 | `2c3a108` |
| [x] | T-M1-02 | `config/loader.py`: Rangfolge CLI > env (`SARA_ABSCHNITT__SCHLUESSEL`) > project.yaml > user > Standard | | 2026-09-30 15:14 | `e5403cc` |
| [x] | T-M1-03 | `project/atomic.py`: atomares Schreiben (`os.replace`, Wiederholung, Ausweichname) | 6 | 2026-09-30 15:15 | `4cacadf` |
| [x] | T-M1-03 | `project/lock.py`: Lock mit Heartbeat, Übernahme veralteter Locks | 2026-09-30 15:17 | `17d426d` | |
| [x] | T-M1-03 | `project/workspace.py`: Ordnerstruktur Kap. 6, Schema-Version | | 2026-09-30 15:17 | `54d3144` |
| [x] | T-M1-04 | `io/readers/detect.py`: Formaterkennung RIS/NBIB/BibTeX/XLSX/ZIP/PDF (Inhalt vor Endung; Typ, Konfidenz, Grund) | 4 | 2026-09-30 15:20 | `55a2f7b` |
| [x] | T-M1-04 | `io/readers/detect.py`: CSV/TSV-Erkennung mit Trennzeichen und Kodierung | | 2026-09-30 15:23 | `4020d3b` |
| [x] | T-M1-05 | `io/readers/base.py`: gemeinsame Typen `RawRecord`/`ReadResult`, Dekodierung mit Kodierungskette | | 2026-09-30 15:24 | `7738aa4` |
| [x] | T-M1-05 | `io/readers/ris.py`: RIS-Reader (Fortsetzungszeilen, L15 beheben; 706/156, 6, 46 laut EXPECTED.json) | 5 | 2026-09-30 15:27 | `a5b819d` |
| [ ] | T-M1-06 | `io/readers/nbib.py`: NBIB/MEDLINE (100 und 62 Datensätze) | 4 | | |
| [ ] | T-M1-07 | `io/readers/bibtex.py`: BibTeX (48, 706; 11,5-MB-Datei nur Marker `large`) | 6 | | |
| [ ] | T-M1-08 | `io/readers/tabular.py`: CSV/TSV/XLSX (Kodierung, Trennzeichen, Spaltenzuordnung) | 5 | | |
| [ ] | T-M1-10 | `io/normalize.py`: Normalisierung auf das Schema von Kap. 26.1 | 5 | | |
| [ ] | T-M1-10 | `io/records_store.py`: `records.csv` schreiben/lesen, SHA-256 der Quellen, Import-Log (E106) | | | |
| [ ] | T-M1-11 | `cli.py`: `sara init`, `sara import`, `sara status` (Exit-Codes Kap. 15.1) | 3 | | |
| [ ] | T-M1-12 | `i18n/texts/de.yaml` + neue Schlüssel (kann jederzeit parallel; auf Wunsch des Projektleiters) | 4 | | |
| [-] | T-M1-09 | PDF-ZIP-Reader (zurückgestellt, ADR 0015: kein Volltext in v1) | 4 | | |

**Meilenstein A erreicht, wenn:** alle Fixtures aus `tests/data/` importierbar sind, die Zahlen `tests/data/EXPECTED.json` entsprechen
und `sara init/import/status` läuft.

### M2 bis M3 (erst nach Meilenstein A; Karten in `tasks/`)

M2: T-M2-01 Dedup, -02 Fuzzy (optional), -03 fehlende Abstracts/Flags, -04 Preflight, -05 Tokenizer/Kosten, -06 Dauer/`sara check`,
-07 PRISMA-Ereignisse, -08 Vorfilter. M3: T-M3-01 Provider-Protokoll + MockProvider, -02 OpenAI-kompatibel (SwissGPT zuerst),
-03 Retry, -04 Rate-Limiter, -05 Prompt-Builder, -06 Antwortschema/Parser, -07 Engine, -08 Checkpoint/Resume, -09 CLI `screen`,
-10 Akzeptanztests. Pro Karte hier Zeilen ergänzen, sobald sie beginnt.

## 5. Nächster Schritt (bitte aktuell halten)

**T-M1-06 (NBIB-Reader `io/readers/nbib.py`)**; T-M1-01 bis T-M1-05 stehen. Alle Reader liefern `ReadResult`/`RawRecord` aus `io/readers/base.py` (Vorbild: `ris.py`); Felder ausserhalb von Kap. 26.1 (`notes`, `database_name` u. a.) muss T-M1-10 nach `extra_json` verschieben. Danach die Reader T-M1-05 (RIS zuerst), -06, -07, -08.

## 6. Abweichungen und offene Punkte

| Datum | Punkt |
|---|---|
| 2026-09-30 | Layer-Vertrag als `ast`-Test statt `import-linter` (neue Abhängigkeit, hätte Rückfrage gebraucht). Bei Bedarf später ersetzen |
| 2026-09-30 | `ruff` schliesst `reference/` aus; portierte Dateien behalten begrenzte Ignore-Regeln (`pyproject.toml`) |
| 2026-09-30 | Remote-Besitzer heisst `trunifom`, GitHub-Benutzer des Projektleiters `trunidom`; Push macht der Projektleiter |
| offen | CI-Matrix (Python 3.13, macOS) ist ungeprüft, bis der erste GitHub-Lauf vorliegt |
| offen | Lizenz des Codes (T-M0-01) und endgültige technische Namen (T-M0-03) |
| offen | Fehlerkatalog (Kap. 26.4) hat keinen Code für "Ordner schon initialisiert / nicht leer"; `Workspace.create` nutzt E404 mit eigener Meldung. Projektleiter soll entscheiden, ob ein neuer Code aufgenommen wird |
