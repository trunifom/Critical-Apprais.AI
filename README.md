# Critical Apprais.AI (Starterpaket)

> **Namenshinweis:** Diese Software heisst **Critical Apprais.AI**. Sie ist der Nachfolger der früheren Software **SARA** (Prototyp und Web-App *SARA-App*), aber **nicht** SARA. Ordner (`SARA-Local`), Python-Paket (`saralocal`) und Befehl (`sara`) tragen noch vorläufige Arbeitsnamen. Details: `docs/NAMING_AND_HISTORY.md`.

Lokale Python-Software für das KI-gestützte Titel-/Abstract-Screening in systematischen Literaturreviews.
**Keine Datenbank, kein Server, keine Konten:** Der Projektordner auf dem Rechner ist die Datenbank. Die Software liest
Literaturexporte (RIS, NBIB, BibTeX, CSV/XLSX, ZIP mit PDFs), schickt jeden Datensatz mit den Ein-/Ausschlusskriterien per API
an ein LLM und schreibt Entscheidung, Begründung und Metadaten in Tabellen (CSV, XLSX) im Projektordner.

Dieser Ordner ist **kein fertiges Produkt**, sondern die Grundlage, um das Projekt aufzusetzen: Spezifikation, übernommener Code,
Testdaten, Tests, Aufgabenkarten und Regeln für KI-Programmier-Agenten.

## Schnellstart

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,import,cli]"
python -m pytest -q          # alle Tests (Anzahl siehe docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md)
python -m ruff check .       # Lint
python -m mypy src              # Typen
```

## Was ist drin

| Ordner / Datei | Zweck |
|---|---|
| `AGENTS.md`, `CLAUDE.md` | Regeln und Einstieg für KI-Agenten |
| `docs/KICKOFF_PROMPT.md` | **Start-Prompt für Programmier-Agenten** (Lesereihenfolge, Git-Einrichtung, Arbeitsablauf) |
| `docs/NAMING_AND_HISTORY.md` | **Name, Vorgeschichte (SARA), Namensregeln** |
| `docs/INDEX.md` | **Landkarte** aller Dokumente + Leseplan je Aufgabe |
| `docs/PROJEKTPLAN.md` | Vollständige Spezifikation (Kap. 1-40): Ziele, Datenmodell, Pipeline, LLM, Formate, GUI, Architektur, Tests, Roadmap |
| `docs/MIGRATION.md` | Welcher alte Code wird wohin übernommen, Status |
| `docs/adr/` | Architekturentscheide |
| `docs/coding/` | Coding-Guidelines (angepasst) |
| `docs/swissgpt/`, `literature/`, `guidelines/`, `reports/`, `imgs/`, `legacy/` | Aus dem bisherigen `docs/`-Ordner übernommen |
| `src/saralocal/` | Neuer Code. Bereits portiert: `enums`, `criteria`, `cost`, `i18n`; neu: `legacy` |
| `tests/` | 47 Tests, Testdaten (`data/`, `data_large/`, `legacy_runs/`, `expected/`), Beschreibung in `tests/README.md` |
| `reference/` | Unveränderte Snapshots von SARA-App und dem Vorgänger `SARA` (nur lesen) |
| `templates/` | Beispiel-`project.yaml`, Modellkatalog, Preistabelle, 5 Prompt-Varianten (YAML) |
| `tasks/` | 33 Aufgabenkarten (M0-M3, ca. 170 h) |
| `assets/` | Lottie-Animationen und Architekturzeichnung (`setup.drawio`/`.png`) der alten App |
| `scripts/` | `plan_chapter.py` (Plankapitel anzeigen), `build_expected.py`, `generate_task_cards.py` |

## So starten Sie mit einem KI-Agenten

1. Agent im Ordner `SARA-Local` (Arbeitsname des Projektordners) öffnen (Claude Code, Codex, Cursor ...). Er liest `AGENTS.md` bzw. `CLAUDE.md`.
2. Auftrag z. B.: *"Bearbeite Aufgabenkarte T-M1-05 (RIS-Reader)."* Die Karte nennt Plankapitel, Wiederverwendung,
   Ergebnisse und Abnahmekriterien.
3. Ergebnis prüfen: `python -m pytest -q`. Commits und Push machen Sie selbst (der Agent committet nur auf Anweisung).

## Vor der Veröffentlichung dieses Ordners (z. B. auf GitHub)

- `docs/literature/`, `docs/guidelines/`, `docs/reports/` und `tests/data_large/test.zip` enthalten fremde bzw. interne
  Dokumente: Lizenz/Vertraulichkeit prüfen oder aus dem Repository ausschliessen (`.gitignore` schliesst nur
  `tests/data_large/` aus).
- `reference/sara-app/sara_statistics/src/inter_rater_reliability.py` enthält einen persönlichen Pfad; nur Referenz.
- Kein API-Schlüssel und keine `secrets.toml` wurden kopiert (siehe Prüfung in der Übergabe).
- Git ist initialisiert (Branch `main`), das Remote `origin` zeigt auf `https://github.com/trunifom/Critical-Apprais.AI.git`. Der Erst-Commit ist lokal erstellt; der Push steht noch aus (nur nach Bestätigung der Projektleitung).
