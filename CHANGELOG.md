# CHANGELOG

Alle wesentlichen Änderungen an Critical Apprais.AI. Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung folgt [SemVer](https://semver.org/lang/de/); solange die Hauptversion 0 ist, können sich Schnittstellen ändern.
Änderungen an persistierten Namen (Spalten, Enum-Werte, Dateinamen) werden hier immer ausdrücklich genannt (Datenvertrag).
Jeder Eintrag verweist auf die Aufgabenkarte; die genauen Commits stehen in `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`.

## [Unveröffentlicht] - 0.0.1

### Zotero-Import, nur lesend (ADR 0030)

Zotero hat eine erreichbare Web-API, die Treffer direkt als RIS- oder BibTeX-Text liefert - genau
die Formate, die dieses Projekt schon lesen kann. `crapai zotero-import` holt deshalb eine
Bibliothek oder Sammlung ab und reicht den Text an die gewöhnliche Import-Pipeline weiter, statt
einen eigenen Parser zu bauen. **Nur lesend:** nichts wird je nach Zotero zurückgeschrieben.

* Neues Paket `src/crapai/zotero/` (`ZoteroClient`, `MockZoteroClient`), neues Extra `zotero`.
* Neues Konfigurationsmodell `zotero:` (`project.yaml`): Bibliothekstyp/-ID, Sammlung, Schlüssel-
  Umgebungsvariable, Format. Kein "enabled"-Schalter - läuft nur über den eigenen Befehl.
* `crapai zotero-import` (CLI) und ein neuer Abschnitt auf der Daten-Seite (Oberfläche).
* Kein eigener "schon synchronisiert"-Mechanismus: die bestehende Duplikat-Erkennung
  (`crapai dedup`) erkennt erneut geholte, bereits bekannte Datensätze wie gewohnt.

### PROSPERO-Protokoll-Entwurf (ADR 0031)

PROSPERO (internationales Register für Review-Protokolle, University of York) hat keine
öffentliche Einreichungs-API - nur ein Webformular. `crapai export mein-review --what prospero`
schreibt deshalb einen **Entwurf** (`.docx`), der so viele Formularfelder wie möglich aus bereits
vorhandenen Projektdaten (Titel, Ziele, Kriterien, Sprach-/Jahreseinschränkungen) vorausfüllt, mit
sichtbarem Platzhalter überall dort, wo PROSPERO mehr erfragt, als dieses Projekt erfasst
(Suchstrategie, Risk-of-Bias-Methode, Synthese-Plan). Keine automatische Einreichung, keine neue
Abhängigkeit (nutzt das bestehende Extra `report`).

* Neues Konfigurationsmodell `prospero:` (`project.yaml`): Start-/Abschlussdatum, Stand, Team,
  korrespondierende Autorin/Autor, Finanzierung, Interessenkonflikte, frühere Registrierung - alle
  Felder leer per Vorgabe, wirken sich auf nichts anderes aus.
* `crapai export --what prospero` (CLI) und eine vierte Auswahl auf der Export-Seite (Oberfläche).

### Optionaler KI-Vorfilter mit Jev (ADR 0029)

Auf Wunsch der Projektleitung recherchiert und als expliziter Spezialmodus umgesetzt: Jev (TypeSafe AI) ist kein Chat-Completion-Modell, sondern beantwortet eine einzige typisierte Ja/Nein-Frage mit kalibrierter Wahrscheinlichkeit, nie mit Fliesstext - also ohne Zitat oder Begründung. Er ersetzt deshalb nie das eigentliche, begründungsfähige Screening, eignet sich aber als schneller, günstiger Vorfilter für klar themenfremde Datensätze.

* **Neuer Befehl `crapai jev-prefilter FOLDER [--yes]`** (eigener Kostenvoranschlag, eigene Bestätigung wie bei `crapai screen`) und eine eigene Oberflächen-Seite - beide bewusst getrennt von `crapai check`/`crapai screen`: der Vorfilter läuft nie automatisch mit.
* **Zwei Tore müssen beide offen sein:** `ai_prefilter.enabled: true` in den Einstellungen (Standard: aus) **und** der separate Start (Befehl oder Seite mit Bestätigungs-Häkchen).
* **Neuer, isolierter Ausschlussgrund `AI_PREFILTER_JEV`**, bewusst ausserhalb der automatischen Dedup-/Vorfilter-/Gültigkeits-Kette, die `crapai check`/`crapai screen` bei jedem Lauf neu berechnen - die Markierung übersteht deshalb jeden weiteren Lauf unverändert.
* Markiert wird nur bei hoher Konfidenz (Standard/Mindestwert 0.9, harte Untergrenze 0.85) und nur als Ausschluss, nie als Einschluss; alles andere geht unverändert ins gewöhnliche Screening.
* PRISMA-Zahlen (`records_removed_by_ai_prefilter`, `ai_prefilter_reasons`) werden korrekt mitgezählt.
* Neues Extra `prefilter-jev = ["httpx"]`; neue Preiszeile in `templates/pricing.example.csv`.

### Durchsicht: Fehlerbehandlung, Protokolle, Dokumentation (Stichwort-Filter, Lauf-Vergleich, Schiedsrichter/Diskussion)

Auf Wunsch der Projektleitung wurden die drei Funktionen der letzten beiden Sitzungen nochmals vertieft durchgesehen (ADR 0025, Nachtrag). Behoben:

* `crapai discuss` prüfte `--runs` erst, nachdem für jeden Teilnehmer schon ein Anbieter (inkl. Schlüsselprüfung) gebaut wurde; ein ungültiger Lauf konnte so einen irreführenden Schlüsselfehler statt der klaren "mindestens zwei Läufe"-Meldung auslösen. Geprüft wird jetzt zuerst.
* Doppelte Lauf-IDs (`--runs run-001,run-001`) waren weder bei `crapai compare-runs` noch bei `adjudicate`/`discuss` ausgeschlossen (ein Lauf "stimmt mit sich selbst überein"); beide weisen das jetzt mit E203 zurück.
* `--max-rounds 0` und ein leerer `--tie-break` wurden von einer `or`-Verknüpfung verschluckt (fielen auf den Standardwert zurück statt abgelehnt zu werden); ein unbekanntes `tie_break` (Tippfehler) verhielt sich unbemerkt wie `majority`. Beides wird jetzt ausdrücklich mit E203 abgelehnt.
* `crapai discuss --resume` verlangte dieselbe Reihenfolge der `--runs` wie beim ursprünglichen Start; der Vergleich ist jetzt mengenbasiert.
* Eine beschädigte oder fehlende `resolution_plan.json` liess `--resume` stillschweigend "alles erledigt" annehmen; das ist jetzt ein klarer `StorageError` E404.
* `discuss --tie-break <falsch>` löste `typer.BadParameter` aus (eigener, nicht übersetzter Fehlerweg); jetzt derselbe `ConfigError`/E203-Weg wie bei den übrigen Befehlen.
* `services/resolution.py` protokolliert jetzt Start, Fortsetzung, Abbruch und Abschluss (fehlte vollständig); `crapai adjudicate`/`discuss` nennen bei einer Pause/Unterbrechung den genauen Fortsetzungsbefehl (wie `crapai screen` es schon tat).

### Uneinigkeit zwischen Läufen klären: Schiedsrichter und Diskussion (ADR 0025)

* **Neuer Befehl `crapai adjudicate --runs <id1,id2,...>`**: ein zusätzliches "Master"-Modell (die aktuellen `llm:`-Einstellungen) liest Datensatz, Kriterien und jede uneinige Meinung (Lauf/Modell, Entscheidung, Begründung) und entscheidet einmal, selbst; gleiches Antwortschema und dieselbe Garantie wie beim Screening (eine unlesbare Antwort wird nie zu einem Entscheid).
* **Neuer Befehl `crapai discuss --runs <id1,id2,...> [--max-rounds N] [--tie-break majority|no_consensus]`**: die ursprünglichen Modelle jedes verglichenen Laufs (rekonstruiert aus **deren eigenem** Manifest, nicht der aktuellen `project.yaml`) sehen die Gegenmeinung und überdenken ihre Entscheidung, bis zu `discussion.max_rounds` Runden (Standard 3). Ohne Konsens entscheidet `discussion.tie_break` (Standard `majority`; ein echtes Patt ergibt immer `NO_CONSENSUS`).
* **Neue Einstellungen** `discussion.max_rounds`, `discussion.tie_break` in `project.yaml` (Abschnitt `discussion:`).
* Eine Klärung wird wie ein gewöhnlicher Lauf gespeichert (`runs/<lauf-id>/`, `manifest.kind` `adjudicate`/`discuss`), ändert `records.csv` nie, ist pausier-/fortsetzbar (`--resume`) und bleibt bewusst aus der gewöhnlichen Auswertung und dem Lauf-Vergleich heraus (`resolvable_runs`, angepasstes `services.results.runs_with_results`).
* **Neue, sonst ungenutzte `ResultRow`-Felder:** `source_decisions`, `consensus`, `rounds_used`, `tie_break`, `history` (keine Schema-Version-Änderung, optionale Felder mit Standardwert). `services/screening.py`: `_new_manifest` speichert neu `base_url`/`api_key_env` (Namen, nie Schlüssel) je Lauf, damit `crapai discuss` jeden Teilnehmer mit seinem eigenen Anbieter aufrufen kann.

### Mehrfachbewertung und Modellvergleich (ADR 0024, Plan Kap. 14.1)

* **Keine Änderung an der Engine:** ein Lauf bleibt ein Provider/Modell; Mehrfachbewertung (Test-Retest oder verschiedene Modelle) bedeutet mehrere separate `crapai screen`-Aufrufe mit angepasster `project.yaml`, jeder mit eigenem `runs/<lauf-id>/` (bestand bereits).
* **Neues Modul `stats/agreement.py`**: paarweise Übereinstimmung und Cohens Kappa je Lauf-Paar, Fleiss' Kappa über alle gewählten Läufe, Einstufung nach Landis & Koch (1977), Liste der uneinigen Datensätze; rein, ohne Dateizugriff. Nur Datensätze mit gültiger Entscheidung (Status `ok`) zählen.
* **Neue Vergleichstabelle** (`stats.results.compare_table`/`compare_columns`): eine Zeile je Datensatz, vier Spalten je Lauf (`status__`, `decision__`, `reasoning__`, `model_returned__<lauf-id>`), Spalte `agreement` (leer/`partial`/`unanimous`/`split`).
* **Neuer Befehl `crapai compare-runs <projekt> --runs <id1,id2,...>`** (`services.results.compare_runs`/`export_comparison`): schreibt `exports/compare-*.csv`/`.xlsx` und gibt die Übereinstimmungszahlen aus; liest nur, ändert nichts.
* **Oberfläche:** neuer Abschnitt „Läufe vergleichen“ auf der Seite Auswertung (ab zwei abgeschlossenen Läufen): Mehrfachauswahl, Tabelle der paarweisen Kennzahlen, Fleiss' Kappa, gruppiertes Balkendiagramm der Entscheidungen **je Lauf in eigener Farbe** (`ui.charts.run_bars`/`run_scale`, neue Farbskala unabhängig von den Ergebniskategorien), Liste der uneinigen Datensätze.

### Stichwort-Filter (ADR 0023)

* **Neuer Vorfilter `prefilters.keywords`** (`KeywordFilter` in `config/models.py`, `prisma/prefilters.py`): durchsucht Title, Abstract und die Felder `keywords`/`keywords_mesh` als einen Text; `exclude_any` schliesst bei Treffer aus, `include_any` ist eine Positivliste (ausgeschlossen, wenn keiner der Begriffe vorkommt), standardmässig ohne Gross-/Kleinschreibung (`case_sensitive`); läuft wie die bestehenden Vorfilter vor dem Modell, ohne Kosten. **Neuer Grund** `PREFILTER_KEYWORD` (Katalog `prisma/reasons.py`, `records_store.EXCLUSION_REASONS`). Aus und ohne Wirkung, solange nichts eingetragen ist.
* **Neue Einstellung `screening.include_keywords_in_prompt`** (Standard `false`): zeigt dem Modell zusätzlich die Stichwörter im `<record>`-Block (`PromptBuilder.build` nimmt neu ein optionales `keywords`-Argument). Ändert den Prompt-Hash nicht, geht aber in den Lauf-Fingerabdruck ein (ein Wechsel während eines Laufs verweigert die Fortsetzung mit E204). Die Kostenschätzung zählt die Stichwörter nur mit, wenn der Schalter an ist.
* Oberfläche (Seite Einstellungen): `prefilters.keywords.include_any`/`exclude_any` als Listenfelder, `screening.include_keywords_in_prompt` als Schalter; `case_sensitive` nur in `project.yaml`.
* Keine Schema-Version-Änderung: `keywords`/`keywords_mesh` waren bereits Spalten von `records.csv`.

### Hinzugefügt

* **Grundlagen (M0):** Lint-Konfiguration (`reference/` ausgenommen), Schichtentest für den Kern (ohne GUI-, CLI- und LLM-Importe), CI-Workflow für Windows/Linux/macOS und Python 3.11-3.13 (T-M0-02).
* **Paketskelett** mit den Unterpaketen `project, io, prisma, screening, llm, prompts, stats, services` (T-M1-01).
* **Fehlerhierarchie** `SaraError` mit Fehlercodes des Katalogs (T-M1-02).
* **Konfiguration `project.yaml`:** geprüfte Modelle (kein API-Schlüssel speicherbar, unbekannte Einstellungen werden abgelehnt, Fehler mit Pfad und Grund, `E201`/`E203`),
  Rangfolge CLI > Umgebung (`CRAPAI_ABSCHNITT__SCHLUESSEL`) > Projekt > Benutzer > Standard (T-M1-02).
* **Projektordner:** atomares Schreiben mit Wiederholung und Ausweichdatei, Sperre mit Herzschlag und Übernahme veralteter Sperren, Ordnerstruktur mit Schema-Version, Warnung bei OneDrive/Dropbox/SharePoint (T-M1-03).
* **Formaterkennung** nach Inhalt (RIS, NBIB, BibTeX, CSV/TSV, XLSX, ZIP, PDF), mit Konfidenz und Begründung (T-M1-04).
* **Reader:** RIS (behebt den Vorgängerfehler L15: Fortsetzungszeilen gingen verloren) (T-M1-05), NBIB/MEDLINE (T-M1-06), BibTeX (tolerant, auch Cochrane-Exporte; 11,5-MB-Datei in etwa 1,5 s) (T-M1-07),
  Tabellen CSV/TSV/XLSX mit Aliasnamen, `--map` und Kodierungserkennung (T-M1-08).
* **Normalisierung und `records.csv`:** 40 Spalten nach Datenvertrag, DOI/Jahr/Listen/Text bereinigt, `EMPTY_RECORD` markiert, Restfelder verlustfrei in `extra_json`,
  verlustfreie Rundreise (Eigenschaftstest), Sicherungen in `data/.backup/`, Import-Protokoll mit SHA-256 und Erkennung erneuter Importe (`E106`) (T-M1-10).
* **Befehle** `crapai init`, `crapai import`, `crapai status` mit Rückgabecodes 0/1/2/4, `--json`, `--lang` (T-M1-11); Import-Dienst und Projektdienst; Vorlagen `blank` und `demo`.
* **Texte** Deutsch und Englisch für Befehlszeile, Oberfläche und alle Fehlercodes (Was ist passiert - Warum - Was tun), Paritätstest (T-M1-12).
* **Dauerschätzung und Kostenausgabe in `crapai check`** (T-M2-06): `cost/duration.py` (langsamste von Anfragen pro Minute, Tokens pro Minute und Anfragedauer/Parallelität; Annahme 3 s je Anfrage), Ausgabe von Modell, Tokens, Kostenband, schlimmstem Fall und Dauer, Warnung (Rückgabecode 4) bei Überschreitung von `limits.max_cost` oder unbrauchbarer `pricing.csv`; `--json` enthält `estimate`. Bestätigungsregel `decide_confirmation` für den späteren Befehl `screen`.
* **Deterministische Vorfilter** (T-M2-08, ADR 0019): `prisma/prefilters.py` und `services/prefilter.py` prüfen Sprache (ISO 639-2, mehrere Sprachen), Jahr (Grenzen einschliesslich) und Publikationstyp vor dem Modell; Markierung mit den neuen Ausschlussgründen `PREFILTER_LANGUAGE`, `PREFILTER_YEAR`, `PREFILTER_TYPE` (Katalog in `records.csv` erweitert, bestehende Werte unverändert); fehlende Angaben nach `on_missing`. `crapai check` führt sie zwischen Dedup und Gültigkeit aus; Dedup darf Vorfiltergründe ersetzen. Im PRISMA-Fluss zählen sie (und ausgeschlossene zurückgezogene Studien) unter "vor dem Screening aus anderen Gründen entfernt".
* **PRISMA-Ereignisse und Flusszahlen** (T-M2-07): `prisma/events.py` (Ereignismodell des Vorgängers ohne Supabase, reine Fabrikfunktionen), `prisma/flow.py` (Portierung von `to_prisma_flow` und `validate_rollup` für beide Berichtsmodi, abgeleitet aus den Ereignissen statt aus einem versteckten Zwischenspeicher), `services/events.py`. Import, Dedup und Gültigkeit schreiben in die neue Datei `data/events.jsonl` (neuer Dateiname im Datenvertrag). Dedup-, Gültigkeits- und Vorfilter-Ereignisse sind Momentaufnahmen, wiederholte Läufe zählen nichts doppelt. Die Zahlen werden gegen den Code des Vorgängers geprüft (Orakeltest inklusive Eigenschaftstest).
* **Kostenschätzung** (T-M2-05, `cost/estimator.py` neu geschrieben): zählt die echten Texte jedes Datensatzes statt einer Stichprobe, Token-Zähler je Anbieter (`tiktoken` für OpenAI, sonst Zeichenzähler mit 10 % Zuschlag; jeder Zähler meldet `exact`), Preisliste `pricing.csv` mit Datum und Quelle (unbekanntes Modell = nur Tokens), Kostenband und Worst Case gegen `limits.max_cost`; Projektdienst `services.cost.estimate_project`. Kein fester Volltext-Wert mehr. Entfernt gegenüber dem Vorgänger: der Hugging-Face-Zähler (Abhängigkeit ausserhalb der Extras), Stichproben und der Modus `per_batch`. Neue Datei im Projektordner: `pricing.csv` (optional).
* **Preflight** (T-M2-04): `crapai check` (Dedup + Gültigkeit, dann Bericht mit Status, Zahlen je Quelle, Gründen und Hinweisen; Rückgabecode 0/4/1; `--read-only`, `--json`) und `check_file` zur Prüfung einer Datei vor dem Import. Ohne Streamlit-Typen, nur Pfade. Die Konfigurationsmeldung nennt jetzt Pfad und Grund des ersten Problems (`crapai status` ebenso).
* **Gültigkeitsprüfung** (T-M2-03, Bausteine `prisma/validity.py`, `services/validity.py`): `NO_ABSTRACT`, `NOT_SCREENABLE` (Front-Matter), `RETRACTED` (optional), `abstract_quality`; gemeinsamer Katalog `prisma/reasons.py`, Duplikate ersetzen Gültigkeitsgründe (ADR 0018). Der Befehl `crapai check` folgt mit T-M2-04.
* **Wiederholbarer Tabellenimport:** `import.mappings` in der `project.yaml` (je Dateiname), Vorrang von `--map`; die Ausgabe nennt die Herkunft der Zuordnung.
* **Duplikate markieren** (`crapai dedup`, T-M2-01): vier Strategien, normalisierte Titel, nicht löschend, behält den vollständigsten Datensatz, im Zweifel keine Markierung, wiederholbar; Statistik innerhalb/zwischen Quellen. `dedup_method` erhält den Wert `pmid` (zu bestätigen).
* **Tests:** Abdeckungsmessung mit Zweigabdeckung (96 % gesamt, neuer Code 99-100 %), `tests/unit/test_edge_cases.py` (37 Randfälle), Wächtertest für Docstrings und Rückgabetypen der öffentlichen API.
* **Lizenz:** PolyForm Noncommercial 1.0.0 (`LICENSE`, ADR 0016, `license` in `pyproject.toml`): nicht kommerzielle Nutzung erlaubt, kommerzielle ausgeschlossen (T-M0-01).
* **Dokumentation:** Benutzerhandbuch, Entwicklerdokumentation, Architektur, ausführliches README, dieses Änderungsprotokoll, Umsetzungsplan mit Fortschrittsliste.

### Oberfläche, zweite Überarbeitung (2026-10-01)

* **Menü** links ausgerichtet; neue Seiten **Übersicht** (Fortschrittsbalken, Stand jedes Schrittes, «Weiter mit …») und **7 · Auswertung**.
* **Einleitung** auf jeder Seite (Ziel, Was passiert, So gehen Sie vor, Ergebnis), einklappbar; lange Seiten in einklappbare Abschnitte gegliedert.
* **Seite Projekt**: Projektbeschrieb, Forschungsfragen, Rahmenwerk (PICOS, SPIDER, PECO, PIRD, eigene) und Ein-/Ausschlusskriterien je Element als Formular (`ui/definition.py`), gespeichert in `project.overrides.yaml`; die Projektdatei ist zugeklappt.
* **Import** in drei nummerierten Schritten mit Liste der importierten Dateien; **Export** in drei Schritten mit Liste und Download aller erzeugten Dateien.
* **Neu: Export der Screening-Ergebnisse** (`crapai export --what results [--run-id]`, CSV/XLSX, `exports/results-*`): eine Zeile je Datensatz mit Ergebniskategorie, Entscheidung, Begründung, Status, Markierungen, Tokens, Kosten.
* **Auswertung** (`stats/results.py`, `services/results.py`, `ui/charts.py`): Diagramme (Ring, Balken, gestapelte Balken, Histogramm, Boxplot, Streudiagramm) und Tabellen aus einem Lauf des Projekts oder aus einer hochgeladenen Exportdatei; Diagramme als Vega-Lite-Beschreibung in den Farben des Designs, ohne neues Paket.
* Streamlit: `crapai ui` setzt die Akzentfarbe (`--theme.primaryColor`) und nutzt `width="stretch"` statt `use_container_width`.

### Oberfläche überarbeitet (2026-10-01)

* **Menü:** Schaltflächen statt Text, in Gruppen (Startseite, Arbeitsablauf 1 bis 6, Weiteres) mit verständlichen Namen; die technischen Seitennamen (`streamlit app`, `check`, `common` ...) sind weg (Ursache war der Ordner `pages/`, den Streamlit selbst als Menü anzeigt; `crapai ui` schaltet das mit `--client.showSidebarNavigation false` aus). Titel steht oben.
* **Sprache bleibt erhalten:** beim Seitenwechsel und beim nächsten Start (`ui_prefs.json`).
* **Hell/Dunkel und Schrift gross/klein** per Schalter; eigenes Stylesheet (`ui/theme.py`), Kontrast jeder Farbpaarung per Test ≥ 4,5:1; einheitliche Schriftgrössen, lange Werte in den Kacheln werden umgebrochen statt abgeschnitten; Tabellen im anderen Design angepasst.
* **Hilfetext zu jedem Bedienelement** (`ui.tip.*`, Deutsch und Englisch, mit Beispielen, auch für alle 47 Einstellungen); ein Test stellt sicher, dass kein Element der Seiten ohne Hilfetext bleibt. Eigene Hinweisboxen (`ui/kit.py`) statt der Streamlit-Meldungen, damit die Farben zum Design passen.
* Neue Dateien: `src/crapai/ui/theme.py`, `src/crapai/ui/kit.py`; neue Datei im Benutzerordner: `ui_prefs.json`.

### Screening mit dem Sprachmodell (M3, ADR 0022)

* **Anbieter-Schicht** (`llm/`): Protokoll `LLMProvider` mit Fehlerklassen, die die Wiederholungsregel tragen (T-M3-01); `MockProvider` mit den 15 Szenarien S1-S15, deterministisch, ohne Netz und Schlüssel; Anbieter für OpenAI und OpenAI-kompatible Dienste wie SwissGPT (T-M3-02, Schlüssel nur aus der Umgebung, SDK-Wiederholungen aus); Wiederholen mit Backoff und `Retry-After` (T-M3-03); gleitender Limiter für Anfragen und Tokens pro Minute, adaptive Parallelität, Schutzschalter (T-M3-04).
* **Prompt und Antwort:** `prompts/builder.py` mit stabilem Anfang, `<record>`-Block und Prompt-Hash, Varianten als YAML im Paket (neue Standardvariante `structured_abstract`, die fünf alten Varianten kopiert) (T-M3-05); `screening/answer.py` prüft das Antwortschema, leitet die Entscheidung zur Gegenprobe aus den Urteilen ab, prüft Zitate und liest das alte XXX/YYY-Format; eine unlesbare Antwort ist ein Fehler, nie ein Einschluss (T-M3-06).
* **Engine** (`screening/engine.py`, T-M3-07/08): Verarbeitung in Päckchen (`run.batch_size`) mit Prüfung der Ergebniszeilen auf der Platte, Fehlerquote je Päckchen, Schutzschalter, Kostenlimit, Stopp mit Nachfrist, genau ein Schreiber; jeder Halt hat Zustand und Code (`paused`, `interrupted`, `failed`); Fortsetzen mit `--resume` überspringt Erledigtes, wiederholt Fehlgeschlagenes und lehnt bei geänderten Einstellungen mit E204 ab; Zähler und Fortschritt sind über den ganzen Lauf kumulativ.
* **Befehle:** `crapai screen` (`--sample`, `--resume`, `--run-id`, `--retry-failed`, `--yes`, `--no-progress`, `--json`) mit Fortschrittsbalken, Kostenrückfrage und Rückgabecodes 0/4/3/1/2 (T-M3-09); `crapai runs`, `crapai pause`, `crapai stop`; `python -m crapai` (neu: `__main__.py`).
* **Oberfläche:** Seite „Lauf“ startet den Lauf als eigenen Prozess (er überlebt das Schliessen des Browsers), zeigt Fortschrittsbalken, Zahlen, Päckchen und Fehler, pausiert, stoppt und setzt fort.
* **Neue Dateien im Projektordner** (Datenvertrag): `runs/<lauf-id>/manifest.json`, `screening.jsonl`, `plan.json`, `control.json`; `.crapai/screen.out`. **Neue Fehlercodes:** E204 (Fortsetzen bei geänderten Einstellungen), E308 (Schutzregel hat den Lauf pausiert). **Neue Einstellungen:** Abschnitt `run:` (elf Werte) und `llm.context_tokens`; `llm.provider` kennt `mock`. Die Kostenschätzung zählt jetzt den echten Prompt der Variante.
* **Akzeptanztests** AT2-AT4 mit dem Mock-Anbieter (AT3 beendet einen echten Arbeitsprozess bei der Hälfte und setzt fort); Live-Test mit echtem Schlüssel ist dokumentiert und ohne Schlüssel übersprungen.
* **Schichtentest:** nur `llm/openai_provider.py` darf `openai` importieren (ausdrückliche Ausnahmeliste); `pytest` läuft mit `asyncio_mode = auto`, Zeilenlänge in Tests nicht begrenzt.

### Einstellungen statt fester Zahlen (ADR 0021)

* **Neue Einstellungen:** `quality.*` (Schwellen der Abstract-Qualität, **`short_abstract_words` jetzt 40 statt 20**), `preflight.min_abstract_ratio`, `limits.seconds_per_request`, `limits.cost_uncertainty`, `llm.expected_output_tokens`, `dedup.fuzzy.max_year_difference`, `dedup.fuzzy.require_author_agreement`. Die Dienste lesen sie aus der Konfiguration.
* **Überschreibdatei `project.overrides.yaml`** und Befehl **`crapai config show|set|reset`**; in der Oberfläche ein Einstellungsformular. `project.yaml` wird nie umgeschrieben. Die wirksame Konfiguration schichtet jetzt auch Umgebungsvariablen und Benutzerdatei (`load_project_config` ruft `resolve_config`).
* **Unscharfe Duplikatsuche** (T-M2-02) ohne Zusatzpaket (`difflib`, optional `rapidfuzz`); die PMID gleicht jetzt auch in der Standard-Strategie, leere PMIDs nie.
* **E405** für `crapai init` in einem belegten Ordner; Rechteinhaber in der LICENSE; `pytest-cov` im Extra `dev` (`scripts/qa.py --cov`); `docs/FREIGABE_CHECKLISTE.md`.

### Oberfläche, Protokoll und Arbeitsablauf

* **Grafische Oberfläche** (`crapai ui`, Extra `ui`): neun Seiten (Start, Projekt, Daten, Prüfen, Lauf, PRISMA-Fluss, Export, Einstellungen, Hilfe) mit Schrittleiste, Statuszeile, Deutsch/Englisch, Fehlern mit Code und nächstem Schritt, Trockenlesung vor dem Import, Kosten und Dauer, Export zum Herunterladen. Lokal (`127.0.0.1`), ohne Nutzungsstatistik. Die Seite „Lauf“ sagt ehrlich, dass das Screening mit dem Sprachmodell noch fehlt.
* **Protokoll-System** (`logging_setup.py`): ein Format mit Sitzungskennung, Schutz vor Schlüsseln und Tokens, `--verbose`/`-v`, Stufe aus `CRAPAI_LOG_LEVEL`, Protokoll in der Oberfläche; eine nicht schreibbare Datei stoppt nichts.
* **Fehlerberichte** (`Messages.error_report`, `ErrorReport`): Befehlszeile und Oberfläche zeigen dieselben Texte; der Hinweis der auslösenden Stelle (zum Beispiel `pip install "crapai[ui]"`) wird an den allgemeinen Rat angehängt statt von ihm verdeckt.
* **Arbeitsablauf:** `python scripts/qa.py` (Lint, Format, Typen, Tests; `--fix`, `--fast`, `--ci`); Tests mit eigenem Heimverzeichnis, ohne `fsync` und ohne Wartezeiten; `project.yaml` wird je Inhalt nur einmal geparst (ein `check` las sie bis zu achtmal); `crapai status` zeigt den Titel auch bei unvollständiger Konfiguration.

### Überarbeitung nach der Gesamtprüfung (ADR 0020)

Drei unabhängige Prüfer lasen den gesamten Code; alle bestätigten Fehler sind behoben und getestet.

* **Neu:** `crapai export` (CSV, XLSX, RIS und PRISMA-Fluss als JSON; Formelschutz, BOM, Ersatzdatei bei gesperrtem Ziel), `crapai unlock` (entfernt eine veraltete Sperre), `dedup.min_title_words`.
* **Datenverlust behoben:** abgerissene letzte Zeile in Import-Protokoll und `events.jsonl` (das nächste Anhängen klebte an, danach war die Datei unlesbar); RIS `DA`, zweite Seitenangaben; BibTeX `date`, `booktitle`, `isbn` und wiederholte Felder; NBIB-Blöcke ohne PMID; BOM bei `--encoding utf-8`; UTF-16-Dateien.
* **Sperre:** unlesbare Sperrdatei galt als veraltet (zwei Schreiber möglich); nicht atomare Übernahme; rohe Fehler; Windows-Handle-Kürzung.
* **PRISMA-Fluss:** Duplikate aus Importsumme abgeleitet (Importe nach dem letzten Dedup wurden als Duplikate gezählt), doppelte Abzüge nach erneutem Dedup, verdoppelte Screening-Läufe, wirkungslose Rechenprobe; neue Warnungen `STALE_*`.
* **Fehlerbehandlung:** `UnicodeDecodeError` in `project.yaml`, Import-Protokoll, `records.csv`, Ereignisdatei und Preisliste; Schreibfehler beim Kopieren nach `sources/`; Protokolldatei nicht schreibbar; `stderr` im JSON-Modus; JSON-Fehlerdokument; Fehler werden mit Code und Meldung (nie Inhalt) protokolliert.
* **Protokoll:** Erfolgszeilen mit Zahlen in Dedup, Vorfilter, Gültigkeit, Schätzung; wiederholtes `check` lässt `events.jsonl` nicht mehr wachsen.
* **Fachlich:** Dedup-Schutz gegen allgemeine Titel, `und`/`mul` als fehlende Sprache, `en-US`, CJK-Abstracts, Preisliste mit Semikolon und jüngstem Datum, Kostenband höchstens 100 %, Kriterienvorlage mit eigenen Elementen, Projekttitel mit Sonderzeichen.
* **Werkzeuge:** `ruff format` auf Paket, Tests und Skripten (CI prüft es), `hatchling>=1.27`, CI bricht überholte Läufe ab.

### Geändert

* **Umbenennung (T-M0-03, ADR 0017):** Kurzform des Produkts ist **CrAp-AI**. Python-Paket `saralocal` → `crapai`, Befehl `sara` → `crapai`, Zustandsordner `.sara/` → `.crapai/`, Umgebungsvariablen `SARA_...` → `CRAPAI_...`, Benutzerkonfiguration `~/.config/sara/` → `~/.config/crapai/`, Distributionsname `sara-local` → `crapai`. **Datenvertrag:** In bereits angelegten Testprojekten muss `.sara` von Hand in `.crapai` umbenannt werden (es gibt noch keine produktiven Projekte); `crapai status` weist darauf hin.
* Die aus dem Vorgänger übernommenen Texte wurden angepasst: kein Volltext-Modus in Version 1, PIRD als Rahmenwerk, keine E-Mail- und Hintergrund-Worker-Texte (T-M1-12).

### Behoben

* Eine fehlende oder nicht lesbare Datei löste in der Formaterkennung eine rohe `FileNotFoundError` aus; jetzt `ImportFailed` `E101` mit klarer Meldung.
* **CI auf GitHub war für alle Testjobs rot** (Lint grün), lokal alle Tests grün. Ursache: Typer erzwingt auf GitHub Actions farbige Ausgabe (`GITHUB_ACTIONS` gesetzt), die Farbcodes zerstückelten die Optionsnamen in `--help`, und vier Tests der Dokumentationsprüfung schlugen fehl. Behoben durch `tests/conftest.py` (kein erzwungenes Terminal), Entfernen der Farbcodes in `test_docs.py` und einen Regressionstest; verifiziert mit nachgestellter CI-Umgebung (611 Tests grün).
* Eine in Excel geöffnete `records.csv` liess den Import zuvor scheinbar gelingen und legte eine Nebendatei an; jetzt bricht der Import mit `E401` ab, ohne etwas zu verändern.

### Bekannte Einschränkungen

* `abstract_quality = suspect_concat` erkennt keine fehlenden Leerzeichen innerhalb gewöhnlich langer Wörter (Cochrane-Beispiel "stressmanagement"): ohne Wörterbuch nicht zuverlässig möglich; die Abnahmebedingung der Karte T-M2-03 ist dafür nicht erfüllbar (ADR 0018).

* Kein Screening, keine Duplikaterkennung, keine grafische Oberfläche (siehe Umsetzungsplan).
* **Unscharfe Duplikatsuche (T-M2-02) ist noch nicht umgesetzt** und bewusst zurückgestellt: sie braucht die neue Abhängigkeit `rapidfuzz` (Freigabe nötig) und eine Prüfliste `reports/possible_duplicates.csv`. Bis dahin findet `crapai dedup` nur exakte und normalisierte Übereinstimmungen.
* Der Rechteinhaber in der Zeile `Required Notice` ist mit der Hochschule zu klären.
* Die CI-Matrix ist noch nicht auf GitHub gelaufen.
