# KICKOFF_PROMPT.md - Start-Prompt für Programmier-Agenten (Critical Apprais.AI)

## So verwenden Sie diese Datei

**Kurzfassung zum Einfügen** (der Agent arbeitet im Ordner `C:\Users\trug\Documents\GitHub\SARA-Local`):

> Du bist ein Programmier-Agent im Projekt **Critical Apprais.AI**. Öffne den Ordner `C:\Users\trug\Documents\GitHub\SARA-Local`, lies
> `docs/KICKOFF_PROMPT.md` vollständig und führe die dort beschriebenen Phasen A bis C in der angegebenen Reihenfolge aus. Halte dich strikt an
> die Stopp-Regeln (Abschnitt 11). Beginne mit dem Verständnis-Check (Abschnitt 6).

**Vollständiger Prompt:** Alles ab der Linie "PROMPT BEGINNT" (Abschnitte 1-14) kann auch direkt als Auftrag eingefügt werden. Er ist so geschrieben, dass
der Agent ohne Rückfrage loslegen kann, aber an definierten Stellen anhält.

**Vorab für Sie (Menschen), drei Dinge klären:**

1. **Remote:** `https://github.com/trunifom/Critical-Apprais.AI.git`. Ein nicht angemeldeter Lesezugriff (`git ls-remote`) lieferte am
   2026-09-30 **keine Referenzen und keinen Fehler**; das Repository wirkt leer und ohne Zugangsschutz beim Lesen (Schluss aus dem Ergebnis, nicht garantiert).
   **Pushen** braucht Ihre Anmeldung (Token oder SSH). Die frühere Anmeldung an `domkuzz/SARA-App` hat wegen eines veralteten Windows-Eintrags und der
   VS-Code-Passwortabfrage nicht funktioniert. Der Agent pusht **nicht** ohne Ihre ausdrückliche Bestätigung und fragt nie nach Tokens.
2. **Git-Identität:** Global ist `trug <trug@zhaw.ch>` gesetzt. Für dieses Repository legen Sie fest, welcher Name/welche E-Mail in die Commits soll
   (der GitHub-Besitzer der URL heisst `trunifom`). Der Agent setzt sie **lokal im Repository**, nie global.
3. **Technische Namen** (Ordner/Paket/Befehl): Solange nicht entschieden, gelten die Arbeitsnamen `SARA-Local` / `crapai` / `crapai` weiter
   (Aufgabe `T-M0-03`). Wenn Sie schon entschieden haben, tragen Sie die Namen unten in Abschnitt 3 ein.

---

# PROMPT BEGINNT

## 1. Rolle und Auftrag

Du bist ein erfahrener Python-Entwickler-Agent. Du baust zusammen mit einem menschlichen Projektleiter die Software **Critical Apprais.AI**:
ein lokales Werkzeug für das KI-gestützte **Titel-/Abstract-Screening in systematischen Literaturreviews**. Deine Aufgaben in dieser Sitzung:

1. **Phase A:** dich orientieren, die Umgebung prüfen, zeigen dass du das Projekt verstanden hast.
2. **Phase B:** das Git-Repository einrichten, mit dem Remote `https://github.com/trunifom/Critical-Apprais.AI.git` verbinden, README und `.gitignore`
   prüfen, alles hinzufügen (`git add`) und den **ersten Commit** erstellen. (Push nur nach Bestätigung, siehe Abschnitt 8.)
3. **Phase C:** die Aufgabenkarten in `tasks/` in der vorgegebenen Reihenfolge abarbeiten, jeweils mit Tests und kleinem, sauberem Commit.

Du arbeitest selbstständig, hältst aber an den Stopp-Stellen (Abschnitt 11) an und fragst. Du erfindest keine Fakten (Modellnamen, Preise, API-Parameter,
Zahlen): Was nicht belegt ist, kommt als `null`/Annahme in eine Datendatei oder wird als Frage gemeldet.

## 2. Worum es geht (Kontext in Kürze)

- **Produktname:** **Critical Apprais.AI** (exakt so schreiben). Es ist **nicht SARA.** Früher gab es die Software **SARA** (Forschungsprototyp) und
  **SARA-App** (Streamlit + Supabase-Web-App, ZHAW, Digital Futures Fund 2024). Diese sind der **Vorgänger**. Critical Apprais.AI ist eine **neue, lokale**
  Software mit demselben fachlichen Ziel. Lies `docs/NAMING_AND_HISTORY.md`.
- **Was die Software tut:** Sie importiert Literaturexporte (RIS, NBIB/MEDLINE, BibTeX, CSV/XLSX), bereitet die Datensätze auf (normalisieren, Duplikate und fehlende
  Abstracts *markieren*, deterministische Vorfilter), schickt jeden Datensatz zusammen mit den Ein-/Ausschlusskriterien per API an ein LLM und schreibt Entscheidung
  (INCLUDE / EXCLUDE / UNCERTAIN), Verdikt je Kriterium und Begründung in Tabellen (CSV, XLSX) im **Projektordner**. Dazu PRISMA-Flusszahlen, Kosten, Statistik
  (Test-Retest, Vergleich mit Menschen).
- **Grundprinzip:** Keine Datenbank, kein Server, keine Konten. **Der Projektordner ist die Datenbank.** Alles läuft lokal; nach aussen geht nur der LLM-API-Aufruf.
- **KI ersetzt keine Menschen:** Ergebnisse sind Vorschläge für die menschliche Prüfung.
- **Warum neu?** Die Evaluation des Vorgängers zeigte: Retest-Stabilität hoch (κ 0,93 bzw. 0,75), aber **Sensitivität nur 8,8 %** gegen Menschen ("Over-Filtering"),
  dazu Bedienprobleme (Kriterien schwer zu formulieren, Ergebnisse als CSV ungeeignet, Sprache als Kriterium nicht erkannt). Details: `docs/PROJEKTPLAN.md` Kap. 35.
  Deshalb: **Sensitivität zuerst**, deterministische Vorfilter, bessere Ergebnisansicht, Evaluation als Kernfunktion.

## 3. Bereits getroffene Entscheidungen (nicht neu aufrollen)

| Thema | Entscheid |
|---|---|
| GUI | **Streamlit** (lokal, `127.0.0.1`). Kern und CLI bleiben GUI-unabhängig. ADR 0013 |
| Umfang Version 1 | **Nur Titel-/Abstract-Screening.** **Kein Volltext** in v1 (später möglich, nur Open-Access-PDFs). ADR 0015. `mode: fulltext` in v1 mit klarer Meldung ablehnen. Aufgabe T-M1-09 ist zurückgestellt |
| LLM-Anbieter | Voraussichtlich vorwiegend **SwissGPT** (AlpineAI) über die OpenAI-kompatible API, `https://api.prod.alpineai.ch/v1`. Laut Spezifikation **ohne `response_format` und ohne `seed`** -> Antworten im Code validieren. OpenAI/Anthropic/lokal bleiben austauschbar. ADR 0014 |
| Lizenzen fremder PDFs | Für die Projektleitung unkritisch (Open Access, Hochschulzugang). Offen bleibt nur die Lizenz des **Codes** |
| Speicherformat | CSV + JSONL kanonisch, XLSX nur Export (ADR 0001-0003) |
| Sprache | Code/Docstrings/Logs/Kommentare **Englisch**; Dokumente in `docs/` **Deutsch** (Schweizer Schreibweise "ss"); UI zweisprachig (en, de) |
| Technische Namen (vorläufig) | Ordner `SARA-Local`, Paket `crapai`, Befehl `crapai`, Zustandsordner `.crapai/`. **Nicht selbst umbenennen** (Aufgabe T-M0-03). Falls der Projektleiter hier Namen einträgt, gelten diese: `<PAKET/CLI/REPO-NAMEN: noch offen>` |

## 4. Umgebung und Repository

- **Arbeitsordner:** `C:\Users\trug\Documents\GitHub\SARA-Local` (Windows 11, PowerShell; Git Bash ist ebenfalls vorhanden). Der Ordner ist **noch kein Git-Repository.**
- **Remote:** `https://github.com/trunifom/Critical-Apprais.AI.git` (angelegt vom Projektleiter, voraussichtlich leer).
- **Python 3.11** ist installiert (`py -3.11`). `ruff` und `mypy` sind nicht vorinstalliert (kommen mit `pip install -e ".[dev]"`).
- **Nicht in den Ordner schreiben oder daraus lesen:** die Nachbarordner `..\SARA-App` und `..\SARA` sind die *Original*-Repositories des Vorgängers. Sie sind **tabu**
  (Kopien liegen bereits in `reference/`). Auch nichts in `~\.gitconfig` (global) ändern.
- **Schlüssel:** Nie API-Schlüssel, Tokens oder Passwörter in Dateien, Commits, Logs, Chat oder Remote-URLs. Keine echten API-Aufrufe ohne ausdrückliche Freigabe.

## 5. Pflichtlektüre in dieser Reihenfolge

Lies vollständig, was mit **[ganz]** markiert ist; sonst nur die genannten Abschnitte. Der Plan (`docs/PROJEKTPLAN.md`, rund 250 KB) ist gross: nutze
`python scripts/plan_chapter.py <Nr>` (z. B. `25.2`), um einzelne Abschnitte zu drucken, und `python scripts/plan_chapter.py` für das Kapitelverzeichnis.

| # | Datei | Was du mitnehmen sollst |
|---|---|---|
| 1 | `AGENTS.md` **[ganz]** | Regeln, goldene Regeln 1-10, Definition of done, was du fragen musst, Stand der Übergabe |
| 2 | `docs/NAMING_AND_HISTORY.md` **[ganz]** | Produktname, SARA = Vorgänger, Namensregeln, vorläufige Arbeitsnamen |
| 3 | `docs/INDEX.md` **[ganz]** | Landkarte, Leseplan je Aufgabe, Herkunft und Aktualität der Dokumente |
| 4 | `docs/coding/coding_guidelines.md` **[ganz]** | Coding-Regeln (Typen, Docstrings, Fehler, async, Dateien, Tests, Git) |
| 5 | `docs/PROJEKTPLAN.md`: Kap. 1, 3, 4, 5.2, 6, 7 | Ziele/Nicht-Ziele, Lehren L1-L18 (Fehler des Vorgängers, **nicht wiederholen**), Architekturentscheide, Projektordner, Datenmodell |
| 6 | `docs/PROJEKTPLAN.md`: Kap. 35 | Ergebnisse und Usability-Erkenntnisse des Vorgängers -> Anforderungen U1-U8 |
| 7 | `docs/PROJEKTPLAN.md`: Kap. 28 (28.1-28.4, 28.7), 39 | Schichten, Prozessmodell, Fehlerhierarchie, Entscheide/offene Punkte |
| 8 | `docs/MIGRATION.md` **[ganz]** | Was ist schon portiert, was wird wohin übernommen |
| 9 | `tasks/README.md` und die Karte der nächsten Aufgabe | Backlog, Abhängigkeiten, Abnahmekriterien |
| 10 | `tests/README.md` und `tests/data/EXPECTED.json` | Testdaten, Sollzahlen (unabhängiges Orakel) |

**Nicht** vollständig lesen (nur bei Bedarf nachschlagen): `reference/**` (alter Code), `docs/legacy/**` (teils veraltet, beschreibt den Vorgänger), die PDFs in
`docs/literature`, `docs/guidelines`, `docs/reports`, `tests/legacy_runs/**`, `tests/data_large/**`.

## 6. Verständnis-Check (gib dies dem Projektleiter aus, bevor du Code schreibst)

Fasse in **höchstens 25 Zeilen** zusammen:

1. Wie heisst das Produkt, was war SARA, wie gehst du mit dem Namen um?
2. Was ist in Version 1 enthalten und was ausdrücklich nicht?
3. Fünf der goldenen Regeln in eigenen Worten (mindestens: nie ein unbrauchbares Modell-Ergebnis in ein Label verwandeln; alles über `study_uid`; nicht-destruktiv;
   `reference/` nie ändern/importieren; keine Geheimnisse).
4. Drei gravierende Fehler des Vorgängers, die du nicht wiederholst (Plan Kap. 3), z. B. L1, L4, L15.
5. Was ist bereits portiert und getestet?
6. Deine Reihenfolge für Phase C (Abschnitt 9) und die erste Aufgabe.

Fahre danach ohne Wartezeit fort, ausser der Projektleiter widerspricht.

## 7. Phase A - Orientierung und Umgebung (Ergebnis: grüne Tests)

Führe aus (PowerShell, im Projektordner):

```powershell
Set-Location "C:\Users\trug\Documents\GitHub\SARA-Local"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q          # erwartet: 47 passed (ca. 5-25 s); ohne tests/data_large: 44 passed, 3 skipped
python -m ruff check .       # Befunde notieren, portierte Dateien sind teilweise ausgenommen
python scripts/plan_chapter.py | Select-Object -Last 8   # Kapitelverzeichnis funktioniert
```

Prüfe außerdem (nur lesen): `git --version`, dass `git status` im Ordner noch "not a git repository" meldet, `tasks/` enthält 33 Karten,
`tests/data/EXPECTED.json` existiert. Wenn Tests fehlschlagen: **nicht beheben, was nicht deine Aufgabe ist**; berichte Fehlermeldung und Ursache.
Bekannte Fallen: Windows-Konsole `cp1252` (Sonderzeichen in `print` -> `sys.stdout.reconfigure(encoding="utf-8")`), `pyarrow` nur für Parquet-Tests, `tests/data_large/`
ist per `.gitignore` nicht versioniert und Tests dazu werden bei Fehlen übersprungen.

**Fertig, wenn:** Umgebung steht, 47 Tests grün, Verständnis-Check ausgegeben.

## 8. Phase B - Git einrichten und erster Commit

Der Projektleiter hat **Commits ausdrücklich freigegeben** (nur diesen ersten Commit und die späteren Aufgaben-Commits gemäss Abschnitt 9). **Pushen ist nicht freigegeben**, ausser er bestätigt es.

### 8.1 Vorprüfung (nur lesen)

```powershell
git --version
git config --global user.name ; git config --global user.email    # nur anzeigen, NICHT ändern
git ls-remote https://github.com/trunifom/Critical-Apprais.AI.git   # nicht interaktiv; leer = Repo hat keine Commits
```

- Kein Ergebnis und kein Fehler: Remote ist erreichbar und leer. Fahre fort.
- Ergebnis mit Referenzen (z. B. `refs/heads/main`): Das Remote hat schon Inhalt (z. B. README/LICENSE aus der GitHub-Oberfläche). **Halte an** und gehe nach 8.5 vor.
- Fehler `could not read Username` / `Authentication failed`: **Halte an.** Das ist ein Anmeldeproblem des Projektleiters, kein Fehler im Projekt. Lege lokal alles an (8.2-8.4), verzichte auf
  Remote-Zugriffe und melde: "Lokal committet, Remote braucht Ihre Anmeldung". Frage nicht nach Tokens, schreibe keine Zugangsdaten in URLs.

### 8.2 Repository anlegen und verbinden (das "Checkout")

```powershell
git init -b main
git remote add origin https://github.com/trunifom/Critical-Apprais.AI.git
git config user.name  "<Name laut Projektleiter>"     # NUR lokal in diesem Repo; frage den Projektleiter, wenn unbekannt
git config user.email "<E-Mail laut Projektleiter>"
git config core.autocrlf false                        # Zeilenenden regelt .gitattributes (Testdaten müssen byte-identisch bleiben)
git config core.longpaths true                        # Windows: Pfade über 260 Zeichen erlauben
git remote -v
```

Wenn Name/E-Mail nicht genannt wurden: **frage nach** (Stopp-Regel), nimm nicht die globale Identität ohne Bestätigung. Danach `git status` (alles "untracked" erwartet).

### 8.3 README und .gitignore prüfen (vor dem Hinzufügen)

1. `README.md`: Namenshinweis oben vorhanden? Schnellstart korrekt? Passt die Aussage "Git ist hier nicht initialisiert" noch? **Aktualisiere den Satz** im Abschnitt
   "Vor der Veröffentlichung" (Repo ist jetzt initialisiert, Remote gesetzt, Push ausstehend). Sonst nichts Inhaltliches ändern.
2. `.gitignore` und `.gitattributes`: bestehen bereits. Prüfe, dass ausgeschlossen sind: `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.env`,
   `tests/data_large/*` (ausser `tests/data_large/README.md`), `.crapai/`, `runs/`. Prüfe, dass `.gitattributes` Testdaten und `reference/**` als `-text` führt
   (Zeilenenden dürfen nicht umgeschrieben werden, sonst schlagen `tests/unit/test_fixture_inventory.py` und `test_legacy_golden.py` auf anderen Rechnern fehl).
   Ergänze bei Bedarf Einträge; entferne nichts.
3. **Keine LICENSE hinzufügen** (Lizenz des Codes ist offen, Aufgabe T-M0-01). Erwähne es im Bericht.

### 8.4 Hinzufügen, prüfen, committen

```powershell
git add -A
git status --short | Measure-Object -Line          # erwartet: genau 200 Dateien (Stand der Übergabe; per Probelauf in einer Kopie geprüft)
git ls-files | ForEach-Object { Get-Item $_ } | Sort-Object Length -Descending | Select-Object -First 8 Name,Length   # grösste Dateien; alle < 5 MB erwartet
git ls-files tests/data_large                        # erwartet nur: tests/data_large/README.md
git diff --cached --name-only | Select-String -Pattern "\.env|secret|\.venv|__pycache__"   # erwartet: keine Treffer
```

Halte an und melde, wenn: eine Datei über 50 MB im Index ist, ein Treffer bei `.env|secret|.venv|__pycache__` erscheint, oder `tests/data_large` mehr als die README enthält.
Sonst:

```powershell
git commit -m "chore: initial import of Critical Apprais.AI starter package" -m "Adds specification (docs/PROJEKTPLAN.md), agent rules (AGENTS.md), read-only reference snapshots of the predecessor SARA/SARA-App, ported modules (enums, criteria, cost, i18n, legacy), 47 tests with fixtures and oracle values, task cards and templates."
git log --stat -1 | Select-Object -First 15
git status                                            # erwartet: working tree clean
python -m pytest -q                                   # Tests nach dem Commit erneut: 47 passed (in einem frischen Klon ohne tests/data_large: 44 passed, 3 skipped - das ist korrekt)
```

Wenn das Projekt eine Commit-Attribution-Vorgabe hat (z. B. "Co-Authored-By"), hänge sie gemäss den Regeln deiner Umgebung an.

### 8.5 Sonderfall: Remote ist nicht leer

`git fetch origin` (nur wenn ohne Anmeldung möglich). Vergleiche `git log origin/main --stat`. Typisch: nur `README.md`, `.gitignore`, `LICENSE` von der GitHub-Oberfläche.
Vorgehen: lokal wie in 8.2-8.4 committen, dann `git merge origin/main --allow-unrelated-histories --no-commit` und Konflikte lösen: **eigene README.md und .gitignore behalten**, eine
vorhandene LICENSE des Remotes **übernehmen** (nicht löschen), dann Merge-Commit. Zeige dem Projektleiter das Ergebnis, bevor du irgendetwas pushst.

### 8.6 Push (nur nach Bestätigung)

Frage: "Soll ich jetzt `git push -u origin main` ausführen?" Erst bei Zustimmung. Scheitert der Push an der Anmeldung: Abbruch, kurze Meldung, Hinweis an den Projektleiter
(Token/SSH einrichten, veralteten Windows-Anmeldeinformationen-Eintrag prüfen). Kein `--force`, keine Tricks (Tokens in URLs, Änderungen an globalen Git-Einstellungen).

**Phase B ist fertig, wenn:** ein sauberer Commit auf `main` existiert, Tests danach grün sind, `git status` sauber ist, und du dem Projektleiter berichtet hast
(Anzahl Dateien, Grösse, Commit-Hash, Remote-Stand, offener Push).

## 9. Phase C - Aufgaben abarbeiten

### 9.1 Reihenfolge

1. **Sofort (ohne weitere Entscheide):** `T-M0-02` (CI, Lint, Layer-Test), `T-M1-01` (Skelett; teilweise erledigt), `T-M1-12` (deutsche Texte, kann jederzeit parallel).
2. **Danach (Abhängigkeiten in den Karten beachten):** `T-M1-02` (Konfiguration/Pydantic), `T-M1-03` (Workspace, Lock), `T-M1-04` (Format-Erkennung).
3. **Reader** `T-M1-05` (RIS, zuerst: dort steckt der gravierende Fehler L15), `T-M1-06` (NBIB), `T-M1-07` (BibTeX), `T-M1-08` (Tabellen). `T-M1-09` (PDF-ZIP) ist **zurückgestellt**, nicht anfassen.
4. `T-M1-10` (Normalisierung, `records.csv`) -> `T-M1-11` (CLI `init`, `import`, `status`).
   **Meilenstein A ("Import steht"):** Die Fixtures aus `tests/data/` lassen sich importieren, Zahlen stimmen mit `EXPECTED.json`, CLI läuft.
5. **M2:** `T-M2-01` bis `T-M2-08` (Dedup, Fuzzy optional, Gültigkeit, Preflight, Kosten, PRISMA-Ereignisse, Vorfilter).
6. **M3 (Screening-Kern):** `T-M3-01` (Provider-Protokoll + Mock), `T-M3-02` (OpenAI-kompatibel/SwissGPT zuerst, dann OpenAI), `T-M3-03` bis `T-M3-10`.
   **Meilenstein B ("Erster Lauf"):** Probelauf mit `MockProvider`, Wiederaufnahme nach Abbruch, Akzeptanztests AT2-AT4 grün.
7. `T-M0-01` (Rest: Ablage/Lizenz) und `T-M0-03` (Umbenennung) nur, wenn der Projektleiter die Entscheide liefert. Frage einmal nach, nicht wiederholt.

Später (M4-M8: Ausgabe/Excel/PRISMA-Grafik, Statistik, Streamlit-Oberfläche, weitere Anbieter, Berichte) folgen Karten, sobald M3 steht.

### 9.2 Arbeitsablauf pro Aufgabe (immer gleich)

1. Karte in `tasks/T-….md` lesen, genannte Plankapitel mit `python scripts/plan_chapter.py <Nr>` lesen, `docs/MIGRATION.md` und die genannten Dateien in `reference/` ansehen.
2. Branch: `git switch -c task/T-M1-05-ris-reader` (Präfix `task/`, Karten-ID, Kurzname).
3. **Test zuerst oder gemeinsam** (Fixtures aus `tests/data/`, Sollzahlen aus `EXPECTED.json`, bei Altergebnissen Golden-Test wie `tests/unit/test_legacy_golden.py`).
4. Implementieren in `src/crapai/...` (portierte Dateien tragen Kopfzeile `# PORTED from SARA-App: <Pfad>` und nennen Änderungen).
5. Prüfen: `python -m pytest -q` (ganz) und `python -m ruff check .`; bei Bedarf `python -m mypy src`.
6. Doku nachführen: Status-Zeile der Karte, `docs/MIGRATION.md` (nur die betroffenen Zeilen), betroffenes Plankapitel, falls sich Verhalten ändert; ADR bei struktureller Entscheidung.
7. Commit (freigegeben): `git add <konkrete Dateien>` (kein blindes `-A` in Phase C), `git diff --cached --name-only` prüfen, dann
   `git commit -m "feat(io): RIS reader with continuation lines and cochrane headers (T-M1-05)"` (Schema `type(scope): Zusammenfassung (Karten-ID)`; Typen: `feat`, `fix`, `test`,
   `docs`, `refactor`, `chore`). Ein Commit pro abgeschlossener Aufgabe; sinnvolle Zwischenschritte dürfen eigene Commits sein.
8. Zurück auf `main` mergen **nur fast-forward oder per Merge-Commit nach Rücksprache**; standardmässig lässt du den Branch stehen und meldest "bereit zum Review".
9. Bericht an den Projektleiter im Format aus Abschnitt 10.

### 9.3 Mehrere Agenten gleichzeitig

- Jeder Agent bearbeitet **eine Karte** und arbeitet im eigenen Branch (besser: eigenes `git worktree`).
- Unabhängig parallelisierbar (nach `T-M1-01`): `T-M1-02`, `T-M1-03`, `T-M1-04`, `T-M1-12`; dann die vier Reader `T-M1-05..08`; in M2 `T-M2-01`, `T-M2-05`, `T-M2-07`; in M3 `T-M3-01`, `T-M3-03`, `T-M3-04`, `T-M3-05`.
- Gemeinsame Dateien nur minimal ändern (`docs/MIGRATION.md`: nur die eigene Zeile; `pyproject.toml`: nur eigene Extras/Abhängigkeiten, vorher fragen; `en.yaml`/`de.yaml`: nur eigene Schlüssel).
- Der zuletzt fertige Agent löst Konflikte beim Merge; niemand überschreibt fremde Änderungen.

## 10. Berichtsformat (nach jeder Phase und Aufgabe)

```
Aufgabe/Phase: T-M1-05 RIS-Reader
Ergebnis:      fertig | teilweise | blockiert
Geändert:      <Dateien, kurz>
Getestet:      pytest: NN passed, ruff: sauber/Befunde; besondere Tests (Golden/Orakel)
Zahlen:        z. B. zotero.ris: 706 Datensätze, 156 mit Abstract (= EXPECTED.json)
Commit:        <Hash> auf Branch <name> (nicht gepusht)
Offen/Risiken: <Punkte>
Frage(n):      <nur wenn Stopp-Regel greift>
Nächster Schritt: <Karte>
```

Kurz und faktisch. Keine Vermutungen als Tatsachen darstellen. Wenn etwas nicht getestet werden konnte, sag es.

## 11. Stopp-Regeln (hier anhalten und den Projektleiter fragen)

- Git-Name/E-Mail für dieses Repo unbekannt; Anmeldung am Remote schlägt fehl; Remote ist nicht leer und der Merge ist nicht trivial; Push steht an.
- Du müsstest eine **neue Abhängigkeit** einführen, die nicht in den Extras von `pyproject.toml` steht.
- Ein Testdatum, `EXPECTED.json` oder ein Vertrag (Spaltennamen, Enum-Werte, JSON-Schlüssel, Dateinamen) müsste geändert werden.
- Ein Plan-Kapitel widerspricht einem anderen oder dem Code; oder ein Abnahmekriterium ist nicht erfüllbar.
- Umbenennung technischer Namen, Änderung von Speicherformaten oder der Schichtregeln.
- Etwas würde Daten an einen externen Dienst senden, Dateien ausserhalb deines Arbeitsordners löschen oder ändern, oder echte API-Schlüssel benötigen.
- Mehr als 3 Versuche für dieselbe Fehlerursache: nicht weiter raten, Befund melden.

## 12. Verbote und Qualitätslatte

- `reference/` **nie ändern und nie importieren**; `tests/data/**`, `tests/legacy_runs/**`, `tests/expected/**` **nie ändern** (nur lesen).
- Kein `print` im Kern (Logging), keine Schlüssel im Log, keine stillen `except: pass`, keine Platzhalterwerte in Daten erfinden (z. B. Jahr 1900).
- Kein Label aus einer unbrauchbaren Modellantwort ableiten (`parse_error` statt `INCLUDE`).
- Keine echten LLM-Aufrufe in Tests; Live-Tests nur mit `@pytest.mark.live` und nur auf Anweisung.
- Kein `git push --force`, kein `git reset --hard` auf fremde Arbeit, kein Umschreiben veröffentlichter Historie, keine globalen Git-Änderungen, kein `--no-verify`.
- Nutzertexte nie mit "SARA" bezeichnen; Produktname aus `crapai.branding.PRODUCT_NAME`.
- Definition of done: siehe `AGENTS.md` Abschnitt 6 (Typen, Docstrings, Tests, ruff, i18n, Fehlercodes, Doku, Kartenstatus).

## 13. Woran du Erfolg erkennst

| Stufe | Erfolgskriterium |
|---|---|
| Phase A | Umgebung läuft, 47 Tests grün, Verständnis-Check abgegeben |
| Phase B | Sauberer Erst-Commit auf `main`, Tests danach grün, Bericht mit Hash, Push-Freigabe eingeholt |
| Meilenstein A | `records.csv` für alle Fixtures mit den Zahlen aus `EXPECTED.json` (z. B. Zotero-RIS 706/156, Cochrane-BibTeX 48, NBIB 100/62), CLI `init`/`import`/`status` |
| Meilenstein B | Probelauf mit MockProvider, Abbruch + `--resume` ohne Doppelbewertung, `parse_error` statt stiller Labels, `results.csv` erzeugt |
| Langfristig | Sensitivität auf einer Pilotmenge gemessen und im Bericht ausgewiesen (Plan Kap. 14, 29.11) |

## 14. Wichtige Pfade und Befehle auf einen Blick

```text
AGENTS.md                      Regeln            docs/NAMING_AND_HISTORY.md   Name/Vorgänger
docs/INDEX.md                  Landkarte         docs/PROJEKTPLAN.md          Spezifikation (Kap. 1-40)
docs/MIGRATION.md              Alt -> Neu        docs/adr/                    Entscheide 0001-0015
tasks/                         33 Karten         templates/                   Beispielkonfiguration, Prompts, Modelle
src/crapai/                 neuer Code        reference/                   Vorgänger-Code (nur lesen)
tests/unit/                    Tests             tests/data/EXPECTED.json     Sollzahlen der Fixtures
```

```powershell
python -m pytest -q                                   # alle Tests
python -m ruff check .                                # Lint
python scripts/plan_chapter.py 25.2                   # Plan-Abschnitt anzeigen
python scripts/build_expected.py                      # EXPECTED.json neu erzeugen (bei neuen Fixtures)
python scripts/generate_task_cards.py                 # Karten neu erzeugen (ÜBERSCHREIBT Status-Zeilen - vorher fragen)
git switch -c task/<ID>-<name>                        # Aufgaben-Branch
```

# PROMPT ENDET
