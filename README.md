# Critical Apprais.AI

> **Namenshinweis:** Diese Software heisst **Critical Apprais.AI**. Sie ist der Nachfolger der früheren Software **SARA** (Prototyp und Web-App *SARA-App*), aber **nicht** SARA.
> Ordner, Python-Paket (`saralocal`) und Befehl (`sara`) tragen noch **vorläufige Arbeitsnamen**; die Umbenennung ist eine eigene Aufgabe (T-M0-03). Details: `docs/NAMING_AND_HISTORY.md`.

Lokale Python-Software für das **KI-gestützte Titel- und Abstract-Screening in systematischen Literaturreviews**.
**Keine Datenbank, kein Server, keine Konten:** Der Projektordner auf Ihrem Rechner ist die Datenbank. Die Software liest Literaturexporte (RIS, NBIB, BibTeX, CSV, XLSX),
bereitet sie auf und wird sie zusammen mit Ihren Ein- und Ausschlusskriterien einem Sprachmodell vorlegen, das **Vorschläge** (Einschluss, Ausschluss, unsicher) mit Begründung liefert.
**Die Ergebnisse ersetzen keine menschliche Prüfung.**

## Stand (Version 0.0.1)

| Bereich | Stand |
|---|---|
| Projekt anlegen, Status (`sara init`, `sara status`) | **umgesetzt** |
| Import RIS, NBIB/MEDLINE, BibTeX, CSV, TSV, XLSX (`sara import`) | **umgesetzt**, getestet gegen unabhängige Sollzahlen |
| Projektordner, atomares Schreiben, Sperre, Sicherungen, Import-Protokoll mit Prüfsummen | **umgesetzt** |
| Konfiguration `project.yaml` (geprüft, Rangfolge CLI > Umgebung > Projekt > Benutzer) | **umgesetzt** |
| Meldungen und Fehlertexte Deutsch/Englisch | **umgesetzt** |
| Duplikate, fehlende Abstracts, Vorfilter, Kostenschätzung (M2) | in Planung |
| Screening mit Sprachmodell, Wiederaufnahme, Ergebnisse, PRISMA (M3-M4) | in Planung |
| Statistik (Test-Retest, Vergleich mit Menschen), Oberfläche (Streamlit) | in Planung |

Meilenstein A („Import steht“) ist erreicht: Alle Beispieldateien in `tests/data/` lassen sich importieren und die Zahlen stimmen mit `tests/data/EXPECTED.json` überein.
Laufender Stand mit Datum und Commit: `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`.

## Grundsätze

* **Lokal.** Nur der Aufruf an den Modellanbieter (später) verlässt den Rechner. Keine Telemetrie. Schlüssel nie in Dateien.
* **Nichts geht still verloren.** Duplikate und Datensätze ohne Abstract werden *markiert*, nie gelöscht. Originaldateien bleiben unverändert (`sources/`).
* **Nie ein Label aus einer unbrauchbaren Modellantwort** (Lehre aus dem Vorgänger): Fehler erhalten einen Status, nie „Einschluss“.
* **Sensitivität zuerst.** Unklare Fälle bleiben zur menschlichen Prüfung erhalten.
* **Nachvollziehbar.** Jeder Datensatz hat eine stabile ID (`study_uid`); jeder Import ist mit Prüfsumme protokolliert.

## Schnellstart

Voraussetzung: Python 3.11 oder neuer.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,import,cli]"

sara init mein-review --from-template demo
sara import mein-review tests/data/example_db_nr2_total-10_duplicates-3.ris --label PubMed
sara status mein-review
```

Ausführlich: **`docs/BENUTZERHANDBUCH.md`**.

## Dokumentation

| Dokument | Für wen | Inhalt |
|---|---|---|
| `docs/BENUTZERHANDBUCH.md` | Forschende, Bibliothekar:innen | Installation, Bedienung, Formate, Fehlermeldungen, häufige Fragen |
| `docs/ENTWICKLERDOKUMENTATION.md` | Entwickler:innen | Umgebung, Schnittstellen, Datenformate, Erweiterungen, Qualitätsregeln, Git-Ablauf |
| `docs/ARCHITEKTUR.md` | Entwickler:innen, Prüfende | Schichten, Module, Datenfluss, Entscheide, Sicherheit, Teststrategie |
| `docs/PROJEKTPLAN.md` | alle | vollständige Spezifikation (Kap. 1-40); einzelne Kapitel: `python scripts/plan_chapter.py 25.2` |
| `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md` | Entwickler:innen, Agenten | abhakbare Liste mit Datum, Uhrzeit, Commit; nächster Schritt |
| `CHANGELOG.md` | alle | Änderungen je Version |
| `AGENTS.md`, `CLAUDE.md` | KI-Agenten | verbindliche Regeln |
| `docs/INDEX.md` | alle | Landkarte aller Dokumente |
| `docs/NAMING_AND_HISTORY.md` | alle | Name, Vorgänger SARA, Namensregeln |
| `docs/MIGRATION.md` | Entwickler:innen | welcher alte Code wurde wohin übernommen |
| `docs/adr/` | Entwickler:innen | Architekturentscheide |
| `docs/coding/coding_guidelines.md` | Entwickler:innen | Coding-Regeln |
| `tests/README.md` | Entwickler:innen | Testdaten und Sollzahlen |

## Aufbau des Repositorys

```
src/saralocal/     Programmcode (Schichten: cli → services → Kern; Details in docs/ARCHITEKTUR.md)
tests/             unit/, integration/, data/ (Beispielexporte + EXPECTED.json), legacy_runs/, expected/
docs/              Dokumentation (Deutsch), adr/, Spezifikation, Fachliteratur
templates/         Beispielkonfiguration, Modellkatalog, Preise, Prompt-Varianten
tasks/             Aufgabenkarten (Backlog)
reference/         Unveränderte Snapshots des Vorgängers (nur lesen, nie importieren)
scripts/           Hilfsskripte (Plankapitel anzeigen, Sollzahlen erzeugen)
.github/workflows/ CI (Ruff, mypy, pytest auf Windows/Linux/macOS, Python 3.11-3.13)
```

## Entwicklung

```powershell
python -m pytest -q         # alle Tests (Anzahl: docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md)
python -m ruff check .      # Lint
python -m mypy src          # Typen
```

* Gearbeitet wird auf `main`; nach jeder fertigen, getesteten Funktion ein Commit mit ausführlicher Nachricht; **gepusht wird durch den Projektleiter**.
* Neue Aufgaben: erste offene Karte in `tasks/` bzw. der nächste Schritt in `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`. Test zuerst oder gemeinsam mit dem Code.
* Nicht ändern: `reference/**`, `tests/data/**`, `tests/legacy_runs/**`, `tests/expected/**`. Persistierte Namen (Spalten, Enum-Werte, Dateinamen) sind Datenverträge.
* Mit einem KI-Agenten: Ordner öffnen; der Agent liest `AGENTS.md` bzw. `CLAUDE.md` und danach `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`.

## Lizenz und Veröffentlichung

* **Lizenz des Codes: [PolyForm Noncommercial 1.0.0](LICENSE)** (ADR 0016). Nutzen, Verändern und Weitergeben sind für **nicht kommerzielle Zwecke** erlaubt, ausdrücklich auch für
  Forschung, Lehre, Hochschulen, öffentliche Einrichtungen und Behörden. Die kommerzielle Nutzung ist ausgeschlossen. Das ist "source available", **keine Open-Source-Lizenz im Sinn der OSI**
  (diese verbietet Nutzungseinschränkungen); im Projektantrag deshalb besser von "frei zugänglich" sprechen. Die Lizenz gilt nur für den eigenen Code und die eigene Dokumentation, nicht für Fremdmaterial
  (`docs/literature/`, `docs/guidelines/`, `docs/reports/`, `docs/swissgpt/`, `reference/`, `tests/data*/`). Wer als Rechteinhaber genannt wird, ist noch mit der Hochschule zu klären (ADR 0016).
* Vor einer öffentlichen Veröffentlichung prüfen: `docs/literature/`, `docs/guidelines/`, `docs/reports/` und `tests/data_large/test.zip` enthalten fremde bzw. interne Dokumente
  (Lizenz/Vertraulichkeit prüfen oder ausschliessen; `.gitignore` schliesst nur `tests/data_large/` aus). Die PubMed-Beispieldateien enthalten öffentliche Korrespondenzadressen von Autor:innen.
* `reference/sara-app/sara_statistics/src/inter_rater_reliability.py` enthält einen persönlichen Pfad; nur Referenz.
* Kein API-Schlüssel und keine `secrets.toml` sind im Repository.
* Remote: `https://github.com/trunifom/Critical-Apprais.AI.git`. Die Git-Identität wird nur lokal im Repository gesetzt.
