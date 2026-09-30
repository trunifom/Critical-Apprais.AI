# BENUTZERHANDBUCH.md - Critical Apprais.AI

Stand: 2026-09-30, Version 0.0.1. Zielgruppe: Forschende und Bibliothekar:innen, die ein systematisches Review durchführen.
Sie brauchen kein Programmierwissen, aber Sie arbeiten mit einem Terminal (Eingabeaufforderung/PowerShell).

> **Wichtig zum Stand:** In dieser Version ist der **Import** und die **Projektverwaltung** nutzbar. Das eigentliche
> KI-Screening (Bewertung durch ein Sprachmodell), Ergebnistabelle, PRISMA-Diagramm und die grafische Oberfläche
> sind **noch nicht verfügbar**. Abschnitte dazu sind als *(geplant)* gekennzeichnet.

## 1. Wozu dient das Programm?

Critical Apprais.AI (früher als Prototyp „SARA“ entwickelt) unterstützt das **Titel- und Abstract-Screening** einer systematischen
Übersichtsarbeit. Es liest Ihre Literaturexporte aus Datenbanken wie PubMed, Embase oder Cochrane, bereitet sie auf, markiert Duplikate
und fehlende Abstracts, und schlägt *(geplant)* mithilfe eines Sprachmodells für jeden Datensatz **Einschluss, Ausschluss oder „unsicher“** vor,
jeweils mit kurzer Begründung je Kriterium.

Grundsätze:

* **Die Ergebnisse sind Vorschläge.** Das Programm ersetzt keine menschliche Prüfung.
* **Alles bleibt auf Ihrem Rechner.** Es gibt keine Datenbank, keinen Server, keine Konten. Ihr Projekt ist ein Ordner. Nur die Aufrufe an den
  Modellanbieter verlassen den Rechner *(geplant)*.
* **Nichts geht still verloren.** Duplikate und Datensätze ohne Abstract werden markiert, nie gelöscht. Ihre Originaldateien bleiben unverändert.
* **Sensitivität zuerst.** Eine übersehene relevante Studie wiegt schwerer als eine überflüssig eingeschlossene; unklare Fälle bleiben deshalb zur Prüfung erhalten.
* Version 1 arbeitet nur mit **Titeln und Abstracts**, nicht mit Volltexten.

## 1a. Lizenz

Die Software darf für **nicht kommerzielle Zwecke** frei genutzt, verändert und weitergegeben werden, ausdrücklich auch in Forschung, Lehre, an Hochschulen, in öffentlichen Einrichtungen und Behörden
(PolyForm Noncommercial 1.0.0, Datei `LICENSE`). Die kommerzielle Nutzung ist ausgeschlossen. Wer die Software kommerziell einsetzen möchte, muss eine Vereinbarung mit den Rechteinhabern treffen.

## 2. Voraussetzungen und Installation

* Windows 11 (macOS und Linux sind vorgesehen), **Python 3.11 oder neuer** (`py -3.11 --version`).
* Installation aus dem Projektordner (PowerShell):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[import,cli]"
crapai --version
```

Ausgabe: `Critical Apprais.AI 0.0.1`. Der Befehl heisst `crapai` (Kurzform des Produkts: CrAp-AI).
Bei jedem neuen Terminal die Umgebung zuerst mit `.\.venv\Scripts\Activate.ps1` aktivieren.

## 3. Schnellstart in fünf Minuten

```powershell
crapai init mein-review --from-template demo        # 1. Projekt anlegen
crapai import mein-review pubmed.ris --label PubMed # 2. Datei importieren
crapai status mein-review                           # 3. Stand ansehen
```

1. **Projekt anlegen.** `mein-review` ist ein neuer Ordner (er darf noch nicht existieren oder muss leer sein). Die Vorlage `demo` enthält ein
   vollständiges Beispielprojekt; die Vorlage `blank` (Standard) legt ein leeres Projekt an, dessen Kriterien Sie noch ausfüllen.
2. **Importieren.** `--label` ist Ihr Name für die Quelle (z. B. die Datenbank). Sie können mehrere Dateien auf einmal angeben.
3. **Status.** Zeigt Anzahl Datensätze, Datensätze mit Abstract, Quellen und ob die Konfiguration in Ordnung ist.

`crapai init` nimmt zusätzlich `--title "Mein Titel"` (Standard: Ordnername) und `--from-template` (Name `blank`/`demo` oder Pfad einer eigenen YAML-Datei).
Deutsche Meldungen erhalten Sie automatisch, wenn in der `project.yaml` `language: de` steht, oder mit `--lang de`.

## 4. Das Projekt (der Ordner)

```
mein-review/
├─ project.yaml              Ihre Einstellungen: Titel, Ziele, Kriterien, Modell, Grenzen
├─ sources/                  Kopien Ihrer Originaldateien (unverändert)
├─ data/
│  ├─ records.csv            alle Datensätze in einer Tabelle
│  ├─ records.import.jsonl   Protokoll der Importe
│  ├─ events.jsonl           Ereignisse für das PRISMA-Flussdiagramm (wird nur ergänzt)
│  └─ .backup/               die letzten 5 Sicherungen von records.csv
├─ runs/  human/  reports/   für spätere Funktionen (Screening-Läufe, menschliche Entscheidungen, Berichte)
└─ .crapai/                    Technisches: Version, Sperre, Protokoll (app.log)
```

* Sie können den Ordner kopieren, zippen und archivieren. Er ist die vollständige Grundlage Ihres Reviews.
* **Aktive Läufe nicht in OneDrive, Dropbox oder SharePoint ablegen.** Synchronisierungsprogramme greifen auf Dateien zu, während das Programm schreibt.
  Das Programm warnt, wenn der Pfad so einen Ordner enthält.
* `records.csv` können Sie in Excel **ansehen**. Ändern Sie sie nicht von Hand (Sicherungen liegen in `data/.backup/`). **Schliessen Sie die Datei in Excel, bevor Sie
  importieren:** Ist sie geöffnet, bricht der Import mit dem Fehler `E401` ab und lässt alles unverändert. Danach können Sie ihn einfach wiederholen.

### 4.1 Die Datei `project.yaml`

Sie enthält, was Sie über Ihr Review festlegen. Die wichtigsten Abschnitte:

| Abschnitt | Inhalt |
|---|---|
| `project` | Titel, Beschreibung, Sprache (`de`/`en`), Modus (`abstract`) |
| `objectives` | Ihre Fragestellungen, eine pro Zeile |
| `criteria` | Rahmenwerk (`PICOS`, `SPIDER`, `PECO`, `PIRD`, `CUSTOM`) und **Einschlusskriterien** (mindestens eines) sowie Ausschlusskriterien |
| `dedup` | Strategie der Duplikaterkennung (`doi_or_title`, `strict_ids`, `title`, `title_authors`) |
| `screening` | Umgang mit „unsicher“ (Standard: einschliessen), Prompt-Variante *(geplant)* |
| `llm` | Anbieter und Modell *(geplant)*; `api_key_env` ist der **Name** der Umgebungsvariable mit Ihrem Schlüssel |
| `limits` | Parallelität, Aufruflimits, Kostenlimit *(geplant)* |
| `import` | `mappings`: gespeicherte Spaltenzuordnung je Tabellendatei, damit ein Import wiederholbar ist (Abschnitt 5.2) |

**Schreiben Sie nie einen API-Schlüssel in die Datei.** Das Programm lehnt so etwas ab. Setzen Sie den Schlüssel als Umgebungsvariable
und tragen Sie nur deren Namen ein (z. B. `SWISSGPT_API_KEY`).

Gute Kriterien sind kurz und prüfbar („Erwachsene ab 18 Jahren“, nicht „geeignete Personen“). Angaben, die sich aus dem Abstract nicht beurteilen lassen
(Sprache, Erscheinungsjahr), gehören später in Filter statt in die Kriterien *(geplant)*.

Fehler in der Datei werden mit Pfad und Grund gemeldet, z. B. `limits.rpm: Input should be greater than 0`.

## 5. Dateien importieren: `crapai import`

```powershell
crapai import mein-review pubmed.ris embase.bib --label PubMed --label Embase
```

### 5.1 Unterstützte Formate

| Format | Endungen | Bemerkung |
|---|---|---|
| RIS | `.ris`, auch `.txt` | EndNote, Zotero, Cochrane, IEEE, Scopus. Mehrzeilige Abstracts werden vollständig gelesen |
| NBIB/MEDLINE | `.nbib`, oft fälschlich `.ris` | PubMed „Send to → Citation manager“ bzw. Format MEDLINE |
| BibTeX | `.bib` | auch die Exporte von Cochrane (mit Zeilen wie `Record #1 of 48`) |
| Tabellen | `.csv`, `.tsv`, `.xlsx` | Spalten wie `title`, `abstract`, `authors`, `year`, `doi` werden automatisch zugeordnet (auch deutsche Namen wie `Titel`) |
| PDF, ZIP | – | nicht Teil von Version 1 |

Das Programm erkennt das Format am **Inhalt**, nicht an der Endung. Beispiel: Eine PubMed-Datei mit der Endung `.ris` wird als NBIB gelesen und Sie erhalten den Hinweis
*„read as nbib although the extension says .ris“*.

### 5.2 Optionen

| Option | Wirkung |
|---|---|
| `--label NAME` | Name der Quelle. Einmal angeben (gilt für alle Dateien) oder einmal pro Datei in der Reihenfolge der Dateien. Ohne Angabe: Dateiname |
| `--map ziel=Spalte` | Tabellen: Spalte selbst zuordnen, z. B. `--map abstract=Zusammenfassung --map title=Name`. Mehrfach möglich. Hat Vorrang vor der gespeicherten Zuordnung |
| `--encoding cp1252` | Zeichenkodierung erzwingen, falls Umlaute falsch erscheinen. Ohne Angabe liest das Programm UTF-8 (auch mit BOM) und UTF-16; ist die Datei kein gültiges UTF-8, nimmt es cp1252 und **sagt es** in einem Hinweis |
| `--delimiter ";"` | Trennzeichen einer CSV-Datei erzwingen: ein Zeichen oder ein Name (`tab`, `semicolon`, `comma`, `pipe`); `E104`, wenn es nicht genau ein Zeichen ist |
| `--sheet Name` | Blatt einer Excel-Datei wählen (Standard: erstes sichtbares) |
| `--force` | Eine bereits importierte Datei nochmals importieren (die Datensätze sind dann doppelt vorhanden) |
| `--json` | Ergebnis maschinenlesbar auf dem Bildschirm (für Skripte) |
| `--lang de` | Sprache der Meldungen |

**Import wiederholbar machen.** Die Ausgabe nennt die verwendeten Spalten (`Verwendete Spalten: title=Name, abstract=Body`, mit `--json` im Feld `column_map`, ebenso im Import-Protokoll).
Tragen Sie diese Zuordnung in die `project.yaml` ein, dann gilt sie beim nächsten Import derselben Datei automatisch, ohne `--map`:

```yaml
import:
  mappings:
    export.csv:            # Dateiname der Quelle
      title: Name
      abstract: Body
```

Die Zuordnung gilt nur für die Datei mit genau diesem Namen. Ein `--map` auf der Befehlszeile hat Vorrang. Stimmt eine Spalte der gespeicherten Zuordnung nicht, erscheint `E104` und es wird nichts importiert.
Das Programm schreibt die `project.yaml` nicht selbst (Ihre Kommentare bleiben erhalten).

### 5.3 Was beim Import geschieht

1. Das Programm berechnet eine Prüfsumme der Datei. Eine Datei mit **gleichem Inhalt** wird nicht ein zweites Mal importiert (Fehler `E106`), auch nicht unter anderem Namen.
2. Format erkennen und lesen. Ist die Datei unbrauchbar, bleibt Ihr Projekt **unverändert**.
3. Die Originaldatei wird nach `sources/` kopiert (nie überschrieben).
4. Jeder Datensatz erhält eine dauerhafte ID (`study_uid`), Texte werden bereinigt (Sonderzeichen, Leerraum), DOI und Jahr vereinheitlicht.
5. `records.csv` wird neu geschrieben (vorher Sicherung), und der Import wird im Protokoll festgehalten.

Nichts wird weggeworfen: Angaben ohne eigene Spalte (z. B. Notizen, Verlag, unbekannte Felder) stehen in der Spalte `extra_json`.
Lokale Dateipfade aus Zotero-Exporten werden nicht in die Auswertungsspalten übernommen.

### 5.4 Warnungen und Rückgabecodes

Nach dem Import erscheinen bei Bedarf Warnungen, und der Rückgabecode ist **4** statt 0:

* *Keiner dieser Datensätze hat einen Abstract* - das Screening braucht Abstracts (oder die Option „nur Titel“ *(geplant)*).
* *Weniger als 60 % haben einen Abstract* - Datensätze ohne Abstract werden nicht bewertet, bleiben aber sichtbar.
* *N Datensätze haben weder Titel noch Abstract* - sie sind in `records.csv` mit `EMPTY_RECORD` markiert.

| Rückgabecode | Bedeutung |
|---|---|
| 0 | in Ordnung |
| 1 | Eingabefehler (falsche Datei, falsche Angabe, kein Projektordner) |
| 2 | Systemproblem (Datei gesperrt, Speicher voll, Projekt in Benutzung, unerwarteter Fehler) |
| 4 | Ergebnis mit Warnungen |

## 6a. Duplikate markieren: `crapai dedup`

```powershell
crapai dedup mein-review                      # Strategie aus der project.yaml
crapai dedup mein-review --strategy title     # andere Strategie
crapai dedup mein-review --keep first         # den ersten statt den vollständigsten behalten
```

Der Befehl **markiert** Duplikate und löscht nichts: Die Zeilenzahl von `records.csv` bleibt gleich. Ein Duplikat erhält `is_duplicate = true`, `duplicate_of` (ID des behaltenen
Datensatzes), `dedup_method` (Grund) und, falls noch keiner gesetzt ist, `exclusion_reason = DUPLICATE`. Duplikate werden später nicht an das Sprachmodell geschickt, bleiben aber sichtbar.

| Strategie | Zwei Datensätze sind Duplikate, wenn … |
|---|---|
| `doi_or_title` (Standard) | sie dieselbe DOI haben, **oder** denselben normalisierten Titel (Gross-/Kleinschreibung, Satzzeichen, Akzente egal). Haben die Titel gleichlautende, die DOIs aber verschiedene Werte, gelten sie **nicht** als Duplikate |
| `strict_ids` | sie dieselbe DOI oder dieselbe PMID haben |
| `title` | der normalisierte Titel gleich ist |
| `title_authors` | normalisierter Titel und normalisierte Autoren gleich sind |

* **Welcher Datensatz bleibt?** Standard `best`: der vollständigste (mit Abstract, dann mit DOI, dann mit PMID), bei Gleichstand der zuerst importierte. Mit `--keep first` oder `--keep last` bestimmen Sie es selbst.
* **Kurze Titel gleichen nie allein.** Ein Titel mit weniger als 4 Wörtern ("Editorial", "Erratum") ist zu allgemein, um eine Studie zu bezeichnen. Gleiche DOI oder PMID erkennt solche Datensätze trotzdem. Einstellung: `dedup.min_title_words` in der `project.yaml` (1 schaltet den Schutz ab). DOIs werden in normalisierter Form verglichen (Gross-/Kleinschreibung, `https://doi.org/` egal).
* **Im Zweifel wird nicht markiert.** Datensätze ohne Titel und ohne DOI werden nie als Duplikate erkannt; ein zu Unrecht markierter Datensatz würde eine Studie verstecken.
* **Wiederholen ist gefahrlos.** Jeder Lauf berechnet die Markierungen neu (frühere Duplikat-Markierungen werden zuerst entfernt); andere Gründe wie `EMPTY_RECORD` bleiben.
* Die Ausgabe nennt, wie viele Duplikate innerhalb derselben Quelle und wie viele zwischen verschiedenen Quellen gefunden wurden. Vor dem Schreiben wird eine Sicherung angelegt.
* `--json` gibt das Ergebnis maschinenlesbar aus. Fehler: `E203` bei unbekannter Strategie, `E402` wenn das Projekt gerade benutzt wird, `E401` wenn `records.csv` in Excel geöffnet ist.

## 6b. Vor dem Lauf prüfen: `crapai check`

```powershell
crapai check mein-review               # Duplikate und Gültigkeit neu berechnen, dann berichten
crapai check mein-review --read-only   # nur berichten, nichts verändern
crapai check mein-review --json        # maschinenlesbar
```

`check` ist die Vorprüfung ("Preflight") vor dem Screening. Sie führt in dieser Reihenfolge aus: Duplikate markieren (`crapai dedup`), dann die Gültigkeit prüfen (fehlende Abstracts,
Vor-/Nachspann, optional zurückgezogene Studien, Abstract-Qualität) und berichtet danach:

* **Kopfzeile mit Status:** *in Ordnung*, *WARNUNG* oder *FEHLER*.
* **Zahlen:** Datensätze, Duplikate, wie viele ans Modell gehen; je Quelle die Zahl der Datensätze, der Anteil mit Abstract, Duplikate und Datensätze, die ans Modell gehen.
* **Gründe**, warum Datensätze nicht ans Modell gehen (`DUPLICATE`, `NO_ABSTRACT`, ...) mit Erklärung. Die Datensätze bleiben in der Tabelle.
* **Hinweise**, zum Beispiel: weniger als 60 % Abstracts in einer Quelle, verdächtig kaputte Abstracts, zurückgezogene Studien, die im Lauf bleiben, oder eine unvollständige `project.yaml`.

| Status | Wann | Rückgabecode |
|---|---|---|
| in Ordnung | nichts zu beanstanden | 0 |
| WARNUNG | Screening ist möglich, aber es gibt Hinweise (siehe oben) | 4 |
| FEHLER | keine Datensätze, oder kein Datensatz kann ans Modell gehen (zum Beispiel keine Abstracts und `include_title_only` ausgeschaltet) | 1 |

Ein Ergebnis "kein Datensatz kann ans Modell gehen" bedeutet nicht, dass etwas gelöscht wurde: Alle Datensätze sind noch da. Ändern Sie die Quellen oder erlauben Sie die Bewertung nur nach Titel
(`screening.include_title_only: true` in der `project.yaml`) und prüfen Sie erneut. Mit `--read-only` wird nichts neu berechnet; das ist sinnvoll, wenn das Projekt gerade von einem anderen Prozess benutzt wird.

Schon **vor** dem Import lässt sich eine einzelne Datei ohne Änderungen prüfen (Lesbarkeit, Anzahl Datensätze, Anteil mit Abstract); das nutzt die spätere grafische Oberfläche.

## 6c. Die Preisliste `pricing.csv`

Für die Kostenschätzung liest Critical Apprais.AI die Datei `pricing.csv` im Projektordner (optional). Preise ändern sich und gehören Ihnen: Tragen Sie die Werte aus der Preisseite Ihres Anbieters ein. Eine Vorlage liegt in `templates/pricing.example.csv` (**die Werte dort sind nur Beispiele**).

```text
provider,model,price_input_per_1k,price_output_per_1k,currency,valid_from,source
anthropic,claude-sonnet-5-5,0.003,0.015,USD,2026-09-30,Preisseite des Anbieters
```

* Preise gelten je 1000 Token. Komma oder Punkt als Dezimalzeichen sind erlaubt; Gross-/Kleinschreibung spielt keine Rolle. Die Datei darf mit Komma **oder Semikolon** getrennt sein (Excel mit deutscher Einstellung speichert mit Semikolon).
* Steht ein Modell in mehreren Zeilen, gilt die Zeile mit dem **jüngsten `valid_from`, das schon erreicht ist**; ein neuer Preis kann also unter den alten geschrieben werden. Zeilen ohne Datum gelten als die ältesten.
* `provider` und `model` müssen mit `llm.provider` und `llm.model` der `project.yaml` übereinstimmen. Ist das Modell nicht eingetragen oder fehlt die Datei, zeigt die Schätzung nur Tokens und keine Kosten.
* Zeilen mit fehlendem oder ungültigem Preis werden übersprungen (Hinweis im Protokoll `.crapai/app.log`). Fehlt eine Pflichtspalte, meldet das Programm `E203`.
* **So wird gezählt:** Jeder Datensatz, der ans Modell geht, wird mit seinem echten Titel und Abstract gezählt, dazu der gemeinsame Anteil (Kriterien, Ziele) einmal je Datensatz. Für OpenAI-Modelle zählt das Programm genau (Paket `tiktoken`, Extra `llm-openai`); für alle anderen Anbieter näherungsweise mit einem Zuschlag von 10 %, damit die Kosten eher zu hoch als zu tief geschätzt werden. Die Ausgabelänge ist unbekannt: Erwartet wird ein Wert pro Antwort, als Obergrenze gilt `llm.max_output_tokens` (Worst Case), der mit `limits.max_cost` verglichen wird.

**Ausgabe in `crapai check`:** Nach dem Bericht zeigt `check` (wenn mindestens ein Datensatz ans Modell geht) Modell, Tokens (genau gezählt oder näherungsweise), das Kostenband mit dem schlimmsten Fall und die geschätzte Dauer. Die Dauer ist die langsamste von drei Grenzen: Anfragen pro Minute (`limits.rpm`), Tokens pro Minute (`limits.tpm`) oder die Zeit einer Anfrage geteilt durch die Parallelität (`limits.max_concurrency`). Für die Zeit einer Anfrage nimmt das Programm **3 Sekunden** an; das ist eine Annahme, die Dauer ist ein Anhaltspunkt und keine Zusage. Liegt der schlimmste Fall über `limits.max_cost`, meldet `check` eine Warnung (Rückgabecode 4), weil ein Lauf vorzeitig stoppen würde. Ist `pricing.csv` unbrauchbar, erscheint eine Warnung statt der Kosten (Rückgabecode 4); die Tokens werden trotzdem gezählt.

**Bestätigung vor dem Lauf:** Der spätere Befehl `crapai screen` startet erst nach einer ausdrücklichen Bestätigung (Kommandozeilen-Option oder Antwort am Terminal); ohne Terminal und ohne Bestätigung startet er nicht (Regel in `cost/duration.py`, getestet).

## 6. Stand ansehen: `crapai status`

```
Projekt: Demo review (example, replace with your own)
Ordner: C:\Reviews\mein-review
Datensätze: 812 (mit Abstract: 798, leer: 0, Duplikate: 0)
Quellen:
  PubMed: 812
Konfiguration: in Ordnung
```

Bei einem leeren oder unvollständigen Projekt erscheint „Die Konfiguration braucht Aufmerksamkeit: …“ mit dem ersten Problem, z. B. fehlende Einschlusskriterien.
`crapai status mein-review --json` liefert dieselben Angaben maschinenlesbar.
Läuft gerade ein anderer Prozess im Projekt, wird das gemeldet.

## 6g. Daten weitergeben: `crapai export`

```powershell
crapai export mein-review                              # alle Datensätze als CSV (Excel-tauglich)
crapai export mein-review --format xlsx --scope screenable
crapai export mein-review --format ris --output fuer-covidence.ris
crapai export mein-review --what flow                  # PRISMA-Flusszahlen als prisma_flow.json
crapai export mein-review --delimiter semicolon        # Semikolon für Excel mit deutscher Einstellung
```

Der Export **verändert das Projekt nicht**. Die Dateien landen im Ordner `exports/` des Projekts, sofern Sie mit `--output` keinen Pfad nennen.

| Option | Bedeutung |
|---|---|
| `--what records` (Standard) / `flow` | Datensätze, oder die PRISMA-Flusszahlen mit Warnungen, Modus und Zahl der zugrunde liegenden Ereignisse |
| `--format csv` (Standard) / `xlsx` / `ris` | Tabellen für Excel; RIS für Literaturverwaltung und Screening-Werkzeuge (Zotero, EndNote, Covidence, Rayyan) |
| `--scope all` (Standard) / `screenable` / `excluded` | alle Datensätze, nur die, die ans Modell gehen, oder nur die mit Ausschlussgrund |
| `--output DATEI` | Zieldatei; der Ordner muss existieren |
| `--delimiter` | CSV-Trennzeichen: `,` `;` `tab` `semicolon`; Standard `,` |
| `--raw` | Zellen, die wie eine Formel beginnen, nicht schützen (siehe unten) |
| `--mode` | nur für `flow`: `all_before_screening` oder `between_databases_only` |

* **CSV** wird mit UTF-8-Kennung (BOM) geschrieben, damit Excel Umlaute richtig zeigt; alle 40 Spalten der `records.csv`. **XLSX** hat eine fixierte, fett gesetzte Kopfzeile mit Filter; dafür braucht es das Paket `openpyxl` (Extra `import`), sonst Fehler `E203`.
* **RIS:** Jeder Datensatz ist ein Eintrag. `ID` trägt die `study_uid` (damit Entscheidungen später den Datensätzen zugeordnet werden können); `N1` nennt Ausschlussgrund, Duplikatsverweis und zurückgezogene Publikation.
* **Schutz vor Formeln (CSV-Injektion):** Ein Titel wie `=HYPERLINK(...)` würde in Excel als Formel laufen. Zellen, die mit `=`, `+`, `-`, `@`, Tabulator oder Zeilenumbruch beginnen, erhalten darum ein vorangestelltes `'` und bleiben Text. Mit `--raw` entfällt der Schutz; öffnen Sie solche Dateien dann nicht in Excel.
* **Datei in Excel geöffnet?** Die Zieldatei wird nicht überschrieben: Der Export wird unter einem Namen mit Zeitstempel gespeichert, das Programm sagt es, und der Rückgabecode ist 4.
* Fehler: `E203` bei unbekanntem Format, Umfang oder Modus oder ungültigem Zielpfad; `E404` für einen Ordner ohne Projekt; `E401`/`E403`, wenn nicht geschrieben werden kann.

## 6f. Veraltete Sperre entfernen: `crapai unlock`

```powershell
crapai unlock mein-review          # fragt nach, bevor die Sperre entfernt wird
crapai unlock mein-review --yes    # ohne Nachfrage (für Skripte)
```

Jeder Befehl, der das Projekt ändert, legt die Sperre `.crapai/lock` an und entfernt sie am Ende. Stürzt ein Lauf ab oder wird er beendet, bleibt die Sperre liegen und alle weiteren
Befehle melden `E402`. `crapai unlock` entfernt sie nur, wenn sie **veraltet** ist: Der Prozess läuft nicht mehr und die Sperre hat seit 60 Sekunden kein Lebenszeichen gezeigt.
Gehört sie einem laufenden Prozess, wird nichts geändert (Rückgabecode 2). Ohne Terminal und ohne `--yes` wird nichts entfernt (Rückgabecode 1). Die Sperre darf **nie** von Hand
gelöscht werden, während ein Lauf aktiv ist.

## 6e. Vorfilter: Sprache, Jahr, Publikationstyp

Manche Kriterien sind Metadaten, die das Sprachmodell nicht zuverlässig beurteilt (zum Beispiel die Sprache einer Studie). Sie prüfen diese im Programm, **vor** dem Modell und ohne Kosten. Die Einstellung steht in der `project.yaml`:

```yaml
prefilters:
  language: { allow: [eng, ger], on_missing: pass }
  year: { min: 2015, max: null, on_missing: pass }
  publication_types: { exclude: [Editorial, Letter, Comment], on_missing: pass }
  exclude_retracted: true
```

* Die Filter laufen automatisch bei `crapai check` (nach den Duplikaten, vor der Gültigkeitsprüfung). Datensätze, die durchfallen, werden **markiert, nicht gelöscht**: `PREFILTER_LANGUAGE`, `PREFILTER_YEAR`, `PREFILTER_TYPE` (Tabelle in 7a); `exclusion_details` sagt genau warum, zum Beispiel `language: fre (allowed: eng, ger)`.
* **Fehlende Angaben:** Fehlt Sprache, Jahr oder Typ, gilt `on_missing`. Mit `pass` (Standard) geht der Datensatz ans Modell, damit nichts wegen fehlender Daten verloren geht; mit `exclude` wird er markiert. Ein Sprachtext wie "n/a" zählt als fehlend.
* **Sprache:** `de`, `deu`, `ger` und `German` sind dasselbe, ebenso `en-US` und `en_GB` für Englisch. Hat ein Datensatz mehrere Sprachen ("eng; fre"), genügt eine erlaubte. Die Marken `und` (unbestimmt), `mul` (mehrere), `zxx`, `unk`, `nan` sagen nichts über die Sprache und zählen als fehlend.
* **Jahr:** Grenzen gelten einschliesslich; `null` heisst offen.
* **Publikationstyp:** Ein Datensatz wird ausgeschlossen, wenn irgendeiner seiner Typen in der Liste steht (Gross-/Kleinschreibung egal). Steht `Editorial` in der Liste, verfällt auch "Journal Article; Editorial".
* Ändern Sie eine Einstellung, berechnet der nächste `crapai check` alles neu; alte Markierungen verschwinden, wenn sie nicht mehr zutreffen.
* Im PRISMA-Fluss zählen diese Datensätze (und ausgeschlossene zurückgezogene Studien) unter "vor dem Screening aus anderen Gründen entfernt" (Abschnitt 6d).

## 6d. Ereignisse und PRISMA-Zahlen

Jeder Import, jede Duplikat-Markierung und jede Gültigkeitsprüfung schreibt eine Zeile in `data/events.jsonl` (was, wann, wie viele). Daraus berechnet das Programm die Zahlen des PRISMA-2020-Flussdiagramms: gefundene Datensätze je Quelle, entfernte Duplikate, vor dem Screening aus anderen Gründen Entfernte, Datensätze zum Screening. Die Datei wird nie umgeschrieben; löschen Sie sie nicht von Hand.

* **Wiederholtes `crapai dedup` zählt nichts doppelt**: pro Quelle gilt der letzte Stand.
* **Zwei Arten, Duplikate zu berichten** (`dedup.reporting_mode` in der `project.yaml`): `all_before_screening` zählt alle Duplikate als "Duplikate entfernt"; `between_databases_only` zählt nur die zwischen verschiedenen Quellen, Duplikate innerhalb einer Quelle erscheinen unter "vor dem Screening aus anderen Gründen entfernt". Die Summe stimmt in beiden Fällen.
* Fehlt ein Ereignis (zum Beispiel weil die Platte voll war), bleibt die Arbeit gültig; `crapai import`, `dedup` und `check` melden das mit einer Warnung (Rückgabecode 4). Führen Sie `crapai check` später erneut aus.
* **Veraltete Zahlen werden gemeldet, nicht verschwiegen.** Importieren Sie nach dem letzten `dedup`, erscheint `STALE_DEDUP`: Die neuen Datensätze zählen dann als "zum Screening" und nicht als Duplikate, bis Sie `crapai check` ausführen. Läuft `dedup` allein nach Vorfilter oder Gültigkeitsprüfung, werden deren ältere Zahlen nicht abgezogen (`STALE_PREFILTER`, `STALE_VALIDITY`), damit nichts doppelt gezählt wird.
* Wiederholtes `crapai check` schreibt nichts Neues, wenn sich nichts geändert hat; die Datei wächst nicht.
* Die Ausgabe als Datei und Grafik (`prisma_flow.json`, `.png`) folgt mit dem Export (M8); die Berechnung selbst steht bereits zur Verfügung.

## 7. Die Tabelle `records.csv` lesen

Wichtigste Spalten:

| Spalte | Bedeutung |
|---|---|
| `study_uid` | dauerhafte ID des Datensatzes (ändert sich nie) |
| `source_label`, `source_file`, `source_row` | woher der Datensatz stammt |
| `title`, `abstract`, `authors`, `year`, `journal`, `doi`, `pmid` | bibliografische Angaben |
| `has_abstract` | `true`/`false` |
| `is_duplicate`, `duplicate_of`, `dedup_method` | Duplikat, Verweis auf den behaltenen Datensatz und Grund (`doi`, `pmid`, `title_norm`, `title_authors`); befüllt durch `crapai dedup` |
| `exclusion_reason`, `exclusion_details` | Grund, warum ein Datensatz nicht ans Modell geht (Tabelle unten). Der Datensatz bleibt trotzdem in der Tabelle |
| `abstract_quality` | Hinweis zum Abstract: `ok`, `short` (unter 20 Wörter) oder `suspect_concat` (verdächtig kaputt oder zusammengeklebt); schliesst nie aus |
| `is_retracted` | „true“, wenn PubMed den Datensatz als zurückgezogen führt |
| `import_notes` | Hinweise des Imports zu diesem Datensatz |
| `extra_json` | alle übrigen Angaben aus der Quelldatei |

Öffnen in Excel: Datei → Öffnen → Textdatei, Kodierung **UTF-8**, Trennzeichen **Komma**, sonst erscheinen Umlaute falsch.

### 7a. Warum ein Datensatz nicht ans Modell geht (`exclusion_reason`)

Jeder Datensatz hat höchstens einen Grund; er wird **markiert, nie gelöscht**. Die Prüfung läuft in dieser Reihenfolge: Import, Duplikate, Vorfilter, Gültigkeit.

| Grund | Bedeutung | Gesetzt durch |
|---|---|---|
| `EMPTY_RECORD` | weder Titel noch Abstract | Import |
| `DUPLICATE` | Duplikat eines anderen Datensatzes (Verweis in `duplicate_of`) | `crapai dedup` |
| `PREFILTER_LANGUAGE` | Sprache nicht in `prefilters.language.allow` (Abschnitt 6e) | Vorfilter |
| `PREFILTER_YEAR` | Jahr ausserhalb von `prefilters.year.min`/`max` | Vorfilter |
| `PREFILTER_TYPE` | ein Publikationstyp steht in `prefilters.publication_types.exclude` | Vorfilter |
| `NOT_SCREENABLE` | kein Studieninhalt, der Titel ist nur "Front-matter", "Index", "Table of contents", "Cover" u. ä. | Gültigkeitsprüfung |
| `RETRACTED` | zurückgezogene Publikation, nur wenn `prefilters.exclude_retracted: true` gesetzt ist | Gültigkeitsprüfung |
| `NO_ABSTRACT` | kein Abstract (ausser bei `screening.include_title_only: true`, dann geht der Titel allein ans Modell) | Gültigkeitsprüfung |
| *(leer)* | geht ans Modell | |

Ein Duplikat ohne Abstract zählt als `DUPLICATE`, nicht als `NO_ABSTRACT` (im PRISMA-Fluss werden Duplikate zuerst entfernt); ein Vorfilter-Grund geht einem Gültigkeitsgrund vor. Zurückgezogene Studien, die nicht ausgeschlossen werden, bleiben im Lauf und
sind über `is_retracted = true` erkennbar. Die Gültigkeitsprüfung wird mit `crapai check` ausgeführt (Abschnitt 6b).

## 8. Fehlermeldungen

Ein Fehler wird in vier Zeilen erklärt: **Fehler CODE: Was ist passiert · Warum · Einzelheiten · Was tun**.

| Code | Bedeutung | Was tun |
|---|---|---|
| E101 | Dateityp nicht erkannt oder nicht unterstützt | Erneut als RIS, NBIB, BibTeX, CSV oder XLSX exportieren |
| E102 | keine Datensätze gefunden | Export prüfen, erneut exportieren |
| E103 | Datei mit dieser Kodierung nicht lesbar | `--encoding cp1252` versuchen |
| E104 | Spalte nicht zuordenbar | `--map abstract=<Spalte>` |
| E106 | Datei bereits importiert | `--force`, falls Sie es wirklich zweimal wollen |
| E201 / E203 | Angabe in der `project.yaml` fehlt / ist ungültig | die genannte Angabe korrigieren |
| E401 | Datei kann nicht geschrieben werden (z. B. `records.csv` ist in Excel geöffnet) | in anderen Programmen schliessen, Rechte prüfen, Befehl wiederholen |
| E402 | Projekt in Benutzung | anderen Lauf beenden; ist keiner aktiv, ist die Sperre veraltet: `crapai unlock mein-review` (Abschnitt 6f) |
| E403 | Speicherplatz voll | Platz schaffen |
| E404 | kein Projektordner dieser Version oder Datei beschädigt | richtigen Ordner wählen, Sicherung aus `data/.backup` verwenden |
| E999 | unerwarteter Fehler | `.crapai/app.log` ansehen und den Fehler melden |

Weitere Codes (E202, E301-E307 Anbieter, E501/E502 Statistik) betreffen Funktionen, die noch folgen.

## 9. Häufige Fragen

**Kann ich dieselbe Datei aus zwei Datenbanken importieren?** Ja, wenn die Dateien verschieden sind. Doppelte Datensätze markieren Sie mit `crapai dedup` (Abschnitt 6a); sie werden nie gelöscht.

**Ich habe die falsche Datei importiert.** Die Originale in `sources/` und die Sicherungen in `data/.backup/` bleiben erhalten. Einen Import rückgängig machen
kann die Software noch nicht; legen Sie in diesem Fall ein neues Projekt an. *(Eine Funktion dafür ist nicht geplant.)*

**Die Umlaute sehen falsch aus.** Bei CSV-Dateien `--encoding cp1252` angeben. `records.csv` ist immer UTF-8.

**Warum sind Angaben in `extra_json`?** Damit nichts verloren geht, auch wenn es keine eigene Spalte gibt.

**Muss ich online sein?** Für Import und Status nicht. Nur das spätere Screening ruft den Modellanbieter auf *(geplant)*.

**Werden meine Daten an Dritte gesendet?** Der Import sendet nichts. Beim späteren Screening gehen Titel und Abstracts an den von Ihnen gewählten Anbieter; das müssen Sie vorher
bestätigen *(geplant)*. Es gibt keine Telemetrie.

## 10. Was noch kommt

Fehlende Abstracts markieren, Vorfilter (Sprache, Jahr, Publikationstyp), Kosten- und Zeitschätzung, das eigentliche Screening mit Wiederaufnahme nach Unterbrechung,
Ergebnistabelle (Excel/CSV), PRISMA-Fluss, Test-Retest und Vergleich mit menschlichen Entscheidungen, und eine grafische Oberfläche. Den Stand finden Sie in
`docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`; die Änderungen je Version in `CHANGELOG.md`.
