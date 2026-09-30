# MIGRATION.md - woher stammt welcher Code, was ist erledigt

Lebendes Dokument. Beim Portieren eines Moduls die Spalte *Status* und *Neues Ziel* aktualisieren.
Stufen: **A** = (fast) unverändert übernehmbar, **B** = übernehmbar mit Anpassungen, **C** = nur Vorlage/Idee,
**D** = nicht übernehmen. Zeilenzahlen = Stand der Snapshots in `reference/`. `L#` = Lehre aus Kapitel 3 des Plans.

## 1. SARA-App (`reference/sara-app/`, Commit siehe `SOURCE_COMMIT.txt`)

| Alter Pfad | Zeilen | Stufe | Neues Ziel | Aufgabe | Status | Bemerkung / Änderungen |
|---|---|---|---|---|---|---|
| `core/enums.py` | 195 | A | `src/crapai/enums.py` | - | **portiert, getestet** | unverändert + Kopfzeile. Werte sind persistiert: nicht ändern |
| `core/estimator.py` | 430 | A | `src/crapai/cost/estimator.py` | T-M2-05 (Ausbau) | **portiert, getestet** | Unverändert. Ausbau: exakte Zählung statt Stichprobe, Tokenizer je Anbieter |
| `core/criteria_template.py` | 348 | A | `src/crapai/criteria/template.py` | - | **portiert, getestet** | Nur i18n-Importpfad geändert |
| `i18n.py` | ~200 | A | `src/crapai/i18n/loader.py` | T-M1-12 | **portiert, getestet** | Fallback-Import geändert, `texts/` liegt im Paket |
| `texts/en.yaml` | 225 | A | `src/crapai/i18n/texts/en.yaml`, `de.yaml` | T-M1-12 | **portiert, angepasst, getestet** | E-Mail-Vorlagen entfernt; Volltext-Abschnitt entfernt (v1), PIRD ergänzt, Hintergrund-Worker/E-Mail-Texte ersetzt. Neu: `nav`, `common`, `start`, `criteria_assistant`, `data`, `run`, `results`, `prisma`, `evaluation`, `settings`, `help`, `cli`, `errors.<Code>.title/cause/action`. `de.yaml` vollständig, Paritätstest `tests/unit/test_i18n_parity.py` |
| `texts/fallback.py` | 238 | A | `src/crapai/i18n/texts/fallback.py` | T-M1-12 | **portiert** | `emails`-Block (SARA-Texte) entfernt |
| `core/prompts.json` | 34 | A | `templates/prompts/*.yaml` | T-M3-05 | **konvertiert** | Text unverändert (Round-Trip geprüft), Container jetzt YAML |
| `core/literature_database.py` | 383 | B | `src/crapai/prisma/dedup.py`, `prisma/validity.py`, `io/records_store.py` | T-M2-01, T-M2-03 | **Dedup (T-M2-01) und Gültigkeit (T-M2-03) neu geschrieben**, Rest offen | Statusspalten und Dedup-Strategien behalten. Dedup: neu geschrieben in `prisma/dedup.py` (normalisierte Titel, leere Titel nie Duplikate, DOI-Konflikte, vollständigster Datensatz). Hilfsfunktionen existieren doppelt (auch in `prisma_workflow.py`) -> zusammenführen. Nicht-destruktiv beibehalten |
| `core/prisma_workflow.py` | 495 | B | `src/crapai/prisma/` | T-M2-01, T-M1-10 | offen | `DedupConfig`, Merge, `get_valid_records_merged`. Snapshots als CSV statt Parquet. Verzeichnis-Nebenwirkung im Konstruktor (`os.makedirs`) vermeiden |
| `core/prisma_logger.py` | 712 | B | `src/crapai/prisma/events.py`, `prisma/flow.py` | T-M2-07 | offen | Ereignismodell, Roll-up, `to_prisma_flow`, `validate_rollup`, `save_json/csv` behalten. `_write_*_to_supabase` und `supabase_client` streichen |
| `core/file_handler.py` | 717 | B | `src/crapai/io/readers/*`, `io/normalize.py` | T-M1-04...T-M1-07, T-M1-10 | offen | Parser übernehmen; **Fehler L15** (Tag-Filter verwirft Fortsetzungszeilen) und **L16** (Streamlit-Import, `bibReader`) beheben. Kodierungserkennung ergänzen |
| `core/preflight.py` | 226 | B | `src/crapai/services/preflight.py` | T-M2-04 | offen | Codes/Enums behalten. Statt `UploadedFile` Pfade. ZIP-Filter (`__MACOSX`, `._`) übernehmen |
| `core/prompt_engine.py` | 100 | C | `src/crapai/prompts/builder.py` | T-M3-05 | offen | Aufbau der Prompts als Idee. Fulltext-Prompt wiederholt Ziele/Kriterien (bewusst, jetzt konfigurierbar) |
| `core/model_query.py` | 202 | C | `src/crapai/llm/*`, `screening/*` | T-M3-01...T-M3-08 | offen | Nur Ideen (System-Prompt, TPM-Fenster). **Nicht kopieren**: L1-L5 (Label-Regel, Retry, Sequenz, Ausrichtung, `st.secrets`) |
| `core/review_worker.py` | 650 | C | `src/crapai/screening/engine.py`, `services/screening.py` | T-M3-07 | offen | Orientierung für den Ablauf (Ingest -> Markieren -> Filter -> Inferenz -> Re-Merge über `study_uid`). Supabase, Polling, Mail entfallen |
| `utils/helpers.py` | 83 | B | `src/crapai/io/pdf_text.py` | T-M1-09 | offen | `extract_text_from_pdf_bytes` (PyMuPDF, Rückfall pdfplumber). `st.secrets` am Modulkopf streichen |
| `utils/graphs.py` | 110 | B | `src/crapai/prisma/diagram.py` | M4 | offen | PRISMA-PNG mit matplotlib. Zahlen aus `prisma_flow.json` statt Wörterbuch mit Platzhaltern |
| `utils/ui_helpers.py` | 272 | B/C | `src/crapai/ui/components.py` | M6 | offen | `render_estimate_metrics`, `render_preflight_table`, `make_estimator`, `warn_if_missing_texts` (Liste `REQUIRED`) |
| `pages/review_setup.py` | 347 | C | `src/crapai/ui/pages/` | M6 | offen | Vorlage für Kriterien-Formular, Upload, Vorprüfung, Kostenpanel, Startbestätigung. Supabase-Teile ersetzen |
| `pages/summary.py` | 94 | C | - | M6 | Negativbeispiel | Feste Beispielzahlen im PRISMA-Diagramm (L18), toter Verweis auf `pages/criteria.py` |
| `pages/home.py` | 83 | C | `src/crapai/ui/pages/start.py` | M6 | offen | Einleitungstext wiederverwendbar |
| `sara_statistics/src/test_retest.py` | 272 | B | `src/crapai/stats/test_retest.py` | M5 | **Kern portiert** | `crapai.legacy` reproduziert die 3 archivierten Berichte (Golden-Test). Ausbau: CLI, Fleiss-Kappa, Berichtsdateien |
| `sara_statistics/src/inter_rater_reliability.py` | 418 | B | `src/crapai/stats/evaluate.py` | M5 | offen | Enthält feste Benutzerpfade (`C:\Users\...OneDrive...`) -> entfernen (L12). Metriken (`calculate_metrics`) behalten, Konfidenzintervalle/WSS ergänzen |
| `sara_statistics/src/config.py` | 25 | D | - | - | - | Pfade -> aus Projektordner |
| `.streamlit/config.toml` | 2 | C | `.streamlit/config.toml` | M6 | offen | Nur `maxUploadSize`. Neues lokales Theme in Plan 27.9 |
| `core/database.py`, `core/mailer/*`, `background/*`, `utils/login_manager.py`, `pages/login.py`, `pages/pw_reset.py`, `main.py` (Auth), `supabase/*`, `render.yaml`, `examples/send_example.py` | - | D | - | - | nicht kopiert (Ausnahme: `render.yaml` als Referenz) | Server/Datenbank/Konten/E-Mail entfallen |

## 2. Vorgänger-Repository `SARA` (`reference/sara-ancestor/`, Commit siehe `SOURCE_COMMIT.txt`)

Herkunft: `github.zhaw.ch/hirsch-lab/SARA`. Dieses Repository ist die Quelle der Dokumente in `docs/` (Coding-Guidelines,
Handbücher, SwissGPT-Spezifikation, Literatur).

| Alter Pfad | Stufe | Verwendung |
|---|---|---|
| `tools/llm_providers.py` (138 Z.) | C | Provider-Registry, `SwissGPTProvider` (Basis-URL `https://api.prod.alpineai.ch/v1`), `AnthropicProvider`, `list_swissgpt_models`. Idee übernehmen, Schwächen beheben: fest codierte Sampling-Werte (0.2/0.9, `max_tokens=1024`), nur `APIConnectionError` abgefangen, synchron, kein Retry |
| `tools/inference.py`, `prompt.py` | C | Überholt durch SARA-App-Code und Plan |
| `tools/literaturdataset.py`, `PRISMAWorkflow.py`, `PRISMAlogger.py`, `processing.py` | D | Vorläufer der SARA-App-Module (dort besser) |
| `tests_unit/test_inference.py` (162 Z.) | C | **Nützliche Vorlage** für das Mocken von OpenAI/Anthropic/SwissGPT (Provider-Umschaltung, Systemprompt-Parameter, fehlendes `anthropic`-Paket) |
| `tests_unit/test_bibliographic_converter.py`, `test_literaturesearchdataset.py` | C | Testideen für Reader/Dedup. Testen alte Klassen (`tools.*`) und laufen hier **nicht** |
| `prompts/` | C | `baseline_abstract.json` (flach) und `prompts_abstract.json` (verschachtelt); durch `templates/prompts/` ersetzt |

## 3. Neu geschrieben (ohne Vorlage im Bestand)

| Modul | Zweck | Test |
|---|---|---|
| `src/crapai/legacy.py` | Alte Läufe lesen (Kodierungs-Fallback), Cohen-Kappa ohne scikit-learn, paarweise Statistik | `tests/unit/test_legacy_golden.py` |
| `scripts/build_expected.py` | Orakel für Datensatzzahlen der Testdaten | `tests/unit/test_fixture_inventory.py` |
| `scripts/generate_task_cards.py`, `scripts/plan_chapter.py` | Backlog und Planlesehilfe | - |
