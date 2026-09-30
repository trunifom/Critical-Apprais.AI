# docs/INDEX.md - Landkarte

Einstieg für Menschen und KI-Agenten. **Projekt: Critical Apprais.AI** (Nachfolger der früheren Software SARA). Regeln für Agenten: `../AGENTS.md`.

## 1. Was liegt wo

| Pfad | Inhalt | Sprache | Verlässlichkeit |
|---|---|---|---|
| `KICKOFF_PROMPT.md` | Start-Prompt für Agenten: Lesereihenfolge, Git-Einrichtung und erster Commit, Arbeitsablauf, Stopp-Regeln | de | **Zum Starten einfügen** |
| `NAMING_AND_HISTORY.md` | Produktname, Kurzform, Vorgeschichte (SARA, SARA-App), Namensregeln, technische Namen | de | **Zuerst lesen** |
| `PROJEKTPLAN.md` | Vollständige Spezifikation: Teil I (Kap. 1-24), Teil II Vertiefung (25-34), Teil III Starterpaket (35-40) | de | **Massgebend** für das neue Projekt |
| `UMSETZUNGSPLAN_UND_FORTSCHRITT.md` | **Übergabeprotokoll:** Fortschrittsliste mit Datum, Uhrzeit und Commit-Hash, nächster Schritt | de | **Lebend, nach jedem Commit pflegen** |
| `BENUTZERHANDBUCH.md` | Bedienung für Forschende (Installation, Befehle, Formate, Fehlermeldungen, FAQ) | de | **aktuell**, wird mit jeder Aufgabe nachgeführt |
| `ENTWICKLERDOKUMENTATION.md` | Software-Dokumentation: Umgebung, Schnittstellen, Datenformate, Erweiterungen, Qualitätsregeln | de | **aktuell** |
| `ARCHITEKTUR.md` | Aufbau: Schichten, Module, Datenfluss, Entscheide, Sicherheit, Tests | de | **aktuell** |
| `../CHANGELOG.md` | Änderungen je Version | de | **aktuell** |
| `MIGRATION.md` | Alter Code -> neues Modul, Status der Portierung | de | lebend, bitte pflegen |
| `adr/` | Architekturentscheide (0001-0015) | de | massgebend |
| `coding/coding_guidelines.md` | Coding-Regeln, **angepasst** (Original daneben: `coding_guidelines.original.md`) | en | Massgebend |
| `swissgpt/` | API-Beschreibung SwissGPT/AlpineAI (`.json` OpenAPI, `.docx`) | en | Herstellerdokument. Zeigt: **kein** `response_format`, **kein** `seed` |
| `literature/` | 2 Fachpapiere zu LLM-gestütztem Screening / Prompting | en | Hintergrund (urheberrechtlich geschützt) |
| `guidelines/` | PRISMA 2020 (Checkliste, erweitert), PRISMA-ScR, BMJ-Artikel zu PRISMA 2020, PICO/SPIDER/SPICE | en | Methodische Grundlage; Vorlage für `crapai report` |
| `reports/` | DFF-Abschlussbericht SARA 2025 (PDF) | de | Projekthintergrund (intern) |
| `imgs/` | `SARA.png` (Logo/Bild) | - | |
| `legacy/` | Handbücher aus früheren Repos (`USER_MANUAL`, `TERMINAL_GUIDE`, `SOFTWARE_ARCHITECTURE`) und README von SARA-App | de/en | **Teilweise veraltet** (siehe Abschnitt 4) |

Ausserhalb von `docs/`: `src/` (neuer Code), `tests/` (Tests + Testdaten, `tests/README.md`), `reference/` (alter Code, nur lesen),
`templates/` (Beispielkonfiguration, Modellkatalog, Prompts), `tasks/` (Aufgabenkarten), `assets/` (Lottie, Architekturzeichnung),
`scripts/` (Hilfsskripte).

## 2. Leseplan je Aufgabe

Kapitel des Plans lesen mit `python scripts/plan_chapter.py <Nr>` (z. B. `25.2`).

| Aufgabe | Lesen |
|---|---|
| Überblick, Ziele, Abgrenzung | Kap. 1, 4, 5 |
| Was macht die alte App genau, welche Fehler hat sie | Kap. 2, 3 |
| Import (RIS/NBIB/BibTeX/CSV/ZIP) | Kap. 25, 26.1, 8.2-8.4; Code: `reference/sara-app/core/file_handler.py`; Daten: `tests/data/` |
| Datenmodell, Spalten, Codes | Kap. 7, 26 |
| Dedup, Abstract-Prüfung, PRISMA-Zahlen | Kap. 8.4, 12; Code: `core/literature_database.py`, `prisma_workflow.py`, `prisma_logger.py` |
| LLM-Anbindung, Limiter, Retry | Kap. 9, 29.3, 28.4, 28.7; `docs/swissgpt/`; `reference/sara-ancestor/tools/llm_providers.py` |
| Prompts, Antwortschema | Kap. 10, 29.5; `templates/prompts/` |
| Checkpoint, Wiederaufnahme, Manifest | Kap. 11, 12.1, 28.4-28.9 |
| Ausgabedateien (XLSX/CSV/RIS/PRISMA) | Kap. 13, 25.8 |
| Statistik/Evaluation | Kap. 14, 29.11; Code: `src/crapai/legacy.py`, `reference/sara-app/sara_statistics/src/` |
| GUI, Layout, Texte | Kap. 27; Code: `reference/sara-app/pages/review_setup.py`, `utils/ui_helpers.py`, `texts/en.yaml` |
| CLI | Kap. 15.1, 27.10 |
| Konfiguration | Kap. 16; `templates/project.example.yaml` |
| Tests | Kap. 18, 33; `tests/README.md` |
| Installation/Betrieb | Kap. 31 |
| Datenschutz/Sicherheit | Kap. 19, 29.10 |
| Wiederverwendung, offene Entscheide | Kap. 35-40, `MIGRATION.md`, `adr/0013-0015` |

## 3. Aktueller Stand (Übergabe 2026-09-30)

- Übergabe 2026-09-30: vier portierte Module, 47 Tests. **Seither:** Meilenstein A (Import) ist erreicht; aktueller Stand und Testzahl stehen in
  `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`.
- Offen: die Aufgabenkarten ab M2 in `tasks/`. Danach M4-M8 gemäss Plan Kap. 21.
- Entschieden am 2026-09-30 (Kap. 39): **Streamlit**, **kein Volltext in v1**, **SwissGPT** als voraussichtlicher Hauptanbieter, Lizenzfragen unkritisch (nur Open-Access-PDFs). Offen: Git-Ablage, Lizenz des Codes.

## 4. Achtung: Herkunft und Aktualität der Dokumente

- `docs/legacy/USER_MANUAL.md`, `TERMINAL_GUIDE.md`, `SOFTWARE_ARCHITECTURE.md` beschreiben das **Vorgänger-Repository `SARA`**
  (Pakete `tools/`, `src/`, `tests/unit`, Python 3.12, Pfade wie `prompts/baseline_abstract.json`), **nicht** SARA-App
  (`core/`, `pages/`). Namen und Pfade stimmen mit `reference/sara-app/` nicht überein. Nützlich sind die Abschnitte zu
  Provider-Umschaltung (SwissGPT/Anthropic), Datenverträgen und methodischen Hinweisen (Evaluierung ohne Überschreiben
  menschlicher Entscheide).
- `docs/legacy/SARA-App_README.md` nennt Dateien, die es nicht (mehr) gibt (`pages/criteria.py`, `utils/data_manager.py`,
  `core/prompts_abstract.json`).
- `docs/coding/coding_guidelines.original.md` stammt aus dem Vorgänger und setzt Flet und SQL voraus.
- `docs/literature/` und `docs/reports/`: urheberrechtlich geschützt bzw. intern. Vor einer Veröffentlichung des Repos prüfen.
