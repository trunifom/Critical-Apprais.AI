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
| ZIP mit PDFs | `.zip` | Volltexte für bereits importierte Datensätze, siehe Abschnitt 5.5 (ADR 0026) |
| einzelne PDF-Datei | `.pdf` | nicht unterstützt; PDFs in ein ZIP packen und das importieren |

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

### 5.5 Volltexte importieren: ZIP mit PDFs

```powershell
crapai import mein-review fulltexte.zip --label Volltexte
```

Für das Volltext-Screening (Abschnitt 6o) werden PDFs **einem bestehenden Datensatz zugeordnet**, nicht als neue Datensätze angelegt: Das Programm liest jede PDF im ZIP (nie auf die Festplatte entpackt), sucht zuerst eine DOI auf der ersten Seite, sonst gleicht es den Titel ab (wie bei `crapai dedup`), und findet so den passenden Datensatz. Der Treffer wird als **neue, zusätzliche Zeile** in `records.csv` gespeichert (`has_fulltext: true`, `fulltext_of: <study_uid des Treffers>`, `zip_member: <Pfad in der ZIP>`); der ursprüngliche Datensatz bleibt unverändert.

* **Ordner und versteckte Dateien** (`__MACOSX/`, `._Datei.pdf`) werden ohne Meldung übersprungen und gezählt; alles ausser `.pdf` ebenso.
* **Kein Treffer:** Die PDF wird nicht verworfen, aber auch nicht als Datensatz angelegt (es gibt ja nichts, dem sie zugeordnet werden könnte) - sie erscheint in `reports/unmatched_pdfs.csv` mit Titel-/DOI-Vermutung, Seitenzahl und Qualität, und der Rückgabecode ist **4** (Warnung).
* **Lesbarkeitsprobleme** einer zugeordneten PDF werden trotzdem gespeichert, mit Grund: `NO_TEXT` (vermutlich gescannt, kein Textlayer - unter 100 Zeichen pro Seite), `ENCRYPTED` (passwortgeschützt) oder `IMPORT_ERROR` (beschädigt oder zu gross, Grenze 50 MB). So unterscheidet das spätere Volltext-Screening "keine PDF gefunden" von "eine PDF wurde gefunden, ist aber nicht lesbar".
* Der Text wird bereinigt (Trennstriche am Zeilenende zusammengezogen, Ligaturen wie „ﬁ“ aufgelöst, wiederkehrende Kopf-/Fusszeilen entfernt) und ab einer Literaturverzeichnis-Überschrift abgeschnitten.

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
* **PMID:** Dieselbe (nicht leere) PMID bedeutet dieselbe Studie; steht bei zwei Datensätzen je eine andere DOI, werden sie nicht zusammengelegt. Datensätze **ohne** PMID (aus Datenbanken, die keine haben) werden nie wegen der leeren PMID als Duplikate erkannt: ein leeres Feld heisst „unbekannt“. Grund in der Tabelle: `pmid`.
* **Unscharfe Suche** (`dedup.fuzzy.enabled: true`): findet zusätzlich Titel, die sich durch einen Tippfehler, ein fehlendes Wort oder eine andere Endung unterscheiden (Grund `fuzzy`). Sie verlangt: Ähnlichkeit mindestens `threshold` (0,94), Erscheinungsjahre höchstens `max_year_difference` (1) auseinander, keine zwei verschiedenen DOIs, gleiche Nachnamen der ersten Autor:innen (wenn beide angegeben sind). Sie braucht kein Zusatzpaket; ist `rapidfuzz` installiert, wird es für mehr Tempo verwendet. **Kurz gesagt:** Sie kann im Zweifel zu viel markieren; prüfen Sie die Duplikate mit Grund `fuzzy`. Gross-/Kleinschreibung, Satzzeichen und Akzente werden bei Titeln immer ignoriert.
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

## 6h. Die grafische Oberfläche: `crapai ui`

```powershell
pip install "crapai[ui]"           # einmalig: installiert Streamlit
crapai ui                          # öffnet die Oberfläche im Browser (Startseite)
crapai ui mein-review              # öffnet gleich dieses Projekt
crapai ui mein-review --port 8600 --no-browser
```

Die Oberfläche läuft **nur auf Ihrem Rechner** (Adresse `127.0.0.1`) und sendet keine Nutzungsstatistik. Sie beendet sich mit Strg+C im Fenster, in dem Sie den Befehl gestartet haben.

| Seite | Was sie tut |
|---|---|
| **Start** | Projekt öffnen (zuletzt verwendete Projekte oder Pfad eingeben) oder neu erstellen (Vorlage, Titel) |
| **Projekt** | Stand des Projekts, Kennzahlen, Quellen; `project.yaml` bearbeiten (wird vor dem Speichern geprüft, bei Fehlern wird nichts geschrieben) |
| **Daten** | Dateien wählen, Trockenlesung mit Format, Zahl der Datensätze und Anteil mit Abstract, Quelle benennen, importieren; Tabelle der Datensätze mit Filter |
| **Prüfen** | Duplikate, Vorfilter und Gültigkeit; Bericht mit Gründen und Hinweisen; Tokens, Kosten (mit schlimmstem Fall) und Dauer |
| **Lauf** | Screening starten, verfolgen, pausieren, stoppen und fortsetzen (Abschnitt 6k) |
| **Übersicht** | Stand aller Schritte und der nächste Schritt (Abschnitt 6h, «Die Seiten im Einzelnen») |
| **Auswertung** | Diagramme und Tabellen der Ergebnisse (Abschnitt 6l) |
| **PRISMA-Fluss** | Zahlen des Flussdiagramms aus den Ereignissen des Projekts, mit Warnungen bei veralteten Schritten |
| **Export** | CSV, XLSX, RIS oder PRISMA-Zahlen erzeugen und herunterladen |
| **Einstellungen** | Pfade, Protokollstufe, Preisliste ansehen |
| **Hilfe** | Datenschutz, Fehlercodes mit Bedeutung, Protokoll des Projekts (aktualisieren, herunterladen) |

* Oben links in der Seitenleiste steht die **Sprache** (Deutsch oder Englisch) und darunter die Schritte mit ihrem Stand: ✅ erledigt, 🔵 als Nächstes, ⚠️ erledigt mit Hinweis, ⚪ noch nicht möglich. Seiten, die noch nicht möglich sind, sagen, was zuerst fehlt.
* Die Kopfzeile jeder Seite zeigt Projekt, Datensätze, Anteil mit Abstract, Duplikate und wie viele ans Modell gehen.
* **Fehler** erscheinen mit Code, Erklärung und nächstem Schritt, nie als Programmfehler-Text; unter „Einzelheiten“ steht ein Text zum Kopieren für eine Fehlermeldung.
* Die Oberfläche verwendet dieselben Funktionen wie die Befehlszeile; es gibt nichts, was nur in einer der beiden geht. Ein Projekt kann gleichzeitig nur von einem Prozess geändert werden (Sperre, Abschnitt 6f).

### Bedienung der Oberfläche: Menü, Anzeige und Hilfe

* **Menü:** Die Seitenleiste beginnt mit dem Titel. Darunter stehen die **Schaltflächen** der Seiten, in Gruppen: *Startseite*; *Arbeitsablauf* in der Reihenfolge der Arbeit (1 Projekt, 2 Daten importieren, 3 Daten prüfen, 4 Screening starten, 5 PRISMA-Fluss, 6 Ergebnisse exportieren) mit Symbolen für den Stand (✅ erledigt, 🔵 als Nächstes, ⚠️ erledigt mit Hinweis, ⚪ noch nicht möglich); *Weiteres* (Einstellungen, Hilfe). Die gerade offene Seite ist farbig gefüllt. Es gibt keine weiteren technischen Menüpunkte.
* **Anzeige:** Direkt unter dem Titel stehen die Sprachauswahl und zwei Schalter: **Hell/Dunkel** und **Schrift gross/klein**. Die Beschriftung nennt, wohin der Klick wechselt. Alle Farben sind auf Lesbarkeit geprüft (mindestens 4,5:1 Kontrast, in beiden Designs). Tabellen werden im anderen Design automatisch angepasst.
* **Gespeichert:** Sprache, Design und Schriftgrösse bleiben beim Seitenwechsel und beim nächsten Start erhalten (Datei `ui_prefs.json` neben der Liste der zuletzt verwendeten Projekte, `~/.config/crapai/`). Ohne gespeicherte Wahl folgt das Design der Einstellung Ihres Browsers.
* **Hilfe zu jedem Bedienelement:** Neben jeder Beschriftung steht ein kleines **?**; fahren Sie mit der Maus darüber (oder tippen Sie darauf) und Sie sehen, was das Feld bewirkt, mit Beispielen. Bei Schaltflächen erscheint der Hilfetext beim Darüberfahren. Das gilt auch für alle Einstellungen im Formular.
* **Hinweise** (Erfolg, Warnung, Fehler) erscheinen als farbige Kästen mit Symbol; die Farben passen zum gewählten Design.

### Die Seiten im Einzelnen: wo gebe ich was ein?

Jede Seite beginnt mit einem einklappbaren Kasten **Über diese Seite** (Ziel, Was passiert, So gehen Sie vor, Ergebnis).

| Ich möchte … | Seite | Wo genau |
|---|---|---|
| wissen, wie weit das Projekt ist und was fehlt | **Übersicht** | Fortschrittsbalken, die Schritte mit Stand und der Knopf «Weiter mit …» |
| den **Projektbeschrieb** schreiben | **1 · Projekt** | Abschnitt «Projektbeschrieb, Forschungsfrage und Kriterien»: Name des Reviews und Kurzbeschreibung |
| die **Forschungsfrage(n)** eintragen | **1 · Projekt** | gleicher Abschnitt, Feld «Forschungsfragen (eine pro Zeile)» |
| **PICOS, SPIDER, PECO, PIRD** oder eigene Elemente wählen | **1 · Projekt** | Auswahl «Rahmenwerk»; für ein eigenes Rahmenwerk die Elementnamen eintragen |
| **Einschluss- und Ausschlusskriterien** festlegen | **1 · Projekt** | zu jedem Element des Rahmenwerks links «Einschluss», rechts «Ausschluss» |
| die Projektdatei von Hand bearbeiten | **1 · Projekt** | zugeklappter Abschnitt «project.yaml bearbeiten» |
| Literaturdateien einlesen | **2 · Daten importieren** | Schritt 1 Dateien wählen, Schritt 2 Quelle benennen, Schritt 3 Importieren |
| Duplikate und Filter prüfen, Kosten schätzen | **3 · Daten prüfen** | Knopf «Prüfung ausführen» |
| Modell, Schlüsselname, Grenzen einstellen | **Einstellungen** | Abschnitte «Sprachmodell», «Lauf», «Grenzen und Kosten» |
| das Screening starten | **4 · Screening starten** | Probelauf, Einverständnis, «Lauf starten» |
| Zahlen für das PRISMA-Diagramm | **5 · PRISMA-Fluss** | Tabelle der Zahlen |
| Dateien herausgeben | **6 · Ergebnisse exportieren** | Datensätze, Screening-Ergebnisse oder PRISMA-Zahlen |
| Ergebnisse grafisch auswerten | **7 · Auswertung** | aus dem Projekt oder aus einer hochgeladenen Exportdatei |

**Projektbeschrieb, Forschungsfrage und Kriterien** werden in `project.overrides.yaml` gespeichert (neben der `project.yaml`); die Projektdatei und ihre Kommentare bleiben unverändert, die gespeicherten Werte haben Vorrang. Gespeichert wird nur, wenn der Name gesetzt ist und bei mindestens einem Element ein Einschlusskriterium steht. Beim Wechsel des Rahmenwerks werden nur die Elemente des neuen Rahmenwerks geschrieben. Das Sprachmodell erhält Beschrieb, Forschungsfragen und Kriterien in jedem Prompt; ändern Sie sie nach einem Lauf, kann dieser Lauf nicht fortgesetzt werden (E204, Abschnitt 6k).

**Import und Export:** Die Seite *Daten importieren* führt in drei nummerierten Schritten und zeigt darunter die Liste der bereits importierten Dateien (Zeitpunkt, Quelle, Zahl der Datensätze). Die Seite *Ergebnisse exportieren* führt ebenfalls in drei Schritten (was, Format und Umfang, exportieren) und listet alle bisher erzeugten Dateien im Ordner `exports/` mit Download.

## 6l. Auswertung: Diagramme und Tabellen

Die Seite **7 · Auswertung** zeigt die Ergebnisse eines Screenings grafisch. Sie liest entweder einen **Lauf des geöffneten Projekts** oder eine **früher exportierte Ergebnisdatei**, auch ohne das Projekt (zum Beispiel nach Abschluss des Reviews oder auf einem anderen Rechner). Es wird nichts verändert und nichts gesendet.

**Ergebnisdatei erzeugen:** Seite *Ergebnisse exportieren*, «Screening-Ergebnisse», CSV oder Excel; oder auf der Befehlszeile:

```powershell
crapai export mein-review --what results --format xlsx          # neuester Lauf mit Ergebnissen
crapai export mein-review --what results --run-id 2026-10-01T14-05_run-003
```

Die Datei hat eine Zeile je Datensatz des Projekts. Wichtige Spalten: `outcome` (Ergebniskategorie), `decision`, `reasoning`, `status`, `flags`, `source_label`, `year`, `abstract_words`, `exclusion_reason`, `tokens_in`, `tokens_out`, `cost`, `latency_s`, `run_id`, `batch`. Beim Hochladen genügt eine Tabelle mit der Spalte `outcome` oder `decision`; fehlende Spalten werden weggelassen, andere Dateien werden mit einer Erklärung abgelehnt (E203). Trennzeichen (Komma, Semikolon, Tabulator) und Zeichenkodierung (UTF-8, Windows) werden erkannt.

**Ergebniskategorien (`outcome`):** *Einschliessen*, *Ausschliessen*, *Unsicher* (Entscheidung des Modells); *Fehler* (an das Modell gesendet, aber ohne gültige Antwort); *Vor dem Modell ausgeschlossen* (Duplikat, Sprache, Jahr, kein Abstract …); *Noch nicht bewertet*.

**Abschnitte** (alle auf- und zuklappbar):

| Abschnitt | Diagramme |
|---|---|
| Entscheidungen im Überblick | Kennzahlen, Ringdiagramm der Anteile, Balkendiagramm der Anzahl |
| Nach Quelle (Datenbank) | gestapelte Balken je Datenbank, auf Wunsch als Anteile |
| Nach Erscheinungsjahr | gestapelte Balken je Jahr |
| Länge der Abstracts | Histogramm, Boxplot je Ergebnis, Streudiagramm Jahr gegen Wortzahl |
| Qualität des Laufs | Status, Markierungen (`inconsistent`, `quote_unverified` …), Stimmigkeit der Entscheidung |
| Kosten, Tokens und Antwortzeit | Tokens je Päckchen, Verteilung der Antwortzeit, Summen |
| Gründe für den Ausschluss vor dem Modell | Balken je Grund |
| Unsichere Datensätze | Liste zur Prüfung durch Menschen |
| Tabelle aller Datensätze | filterbar nach Ergebnis, als CSV herunterladbar |

Die Farben der Ergebnisse sind in beiden Designs unterscheidbar; die Diagramme folgen dem gewählten Design und der Schriftgrösse. Zeigen Sie mit der Maus auf Balken oder Punkte, um die Zahlen zu sehen.

## 6m. Mehrfachbewertung und Modellvergleich: `crapai compare-runs`

Dasselbe Projekt kann mehrfach bewertet werden - mit demselben Modell (Test-Retest) oder mit verschiedenen Modellen (Modellvergleich). Jede Bewertung ist ein **eigener, unabhängiger Lauf** (`crapai screen`): einfach `project.yaml` zwischen den Läufen anpassen (`llm.provider`/`llm.model`, auf der Befehlszeile oder in der Oberfläche) und `crapai screen` erneut ausführen. Die Läufe teilen sich nur die Eingabedaten, sonst nichts; jeder hat sein eigenes Manifest und seinen eigenen Ordner `runs/<lauf-id>/`.

```powershell
crapai screen mein-review                      # Lauf 1: z. B. SwissGPT Neotron
# project.yaml anpassen: llm.model auf das zweite Modell setzen (z. B. ChatGPT GPT-4o)
crapai screen mein-review                      # Lauf 2
crapai runs mein-review                        # zeigt die Lauf-IDs
crapai compare-runs mein-review --runs run-001,run-002 --format xlsx
```

`crapai compare-runs` vergleicht zwei oder mehr abgeschlossene Läufe:

* **Tabelle** (`exports/compare-<läufe>-<zeitstempel>.csv`/`.xlsx`): eine Zeile je Datensatz des Projekts, mit `study_uid`, `title`, `year`, `journal`, `exclusion_reason` und je Lauf vier Spalten (`status__<lauf-id>`, `decision__<lauf-id>`, `reasoning__<lauf-id>`, `model_returned__<lauf-id>`); zusätzlich `agreement`: leer (weniger als zwei Läufe haben entschieden), `partial` (nicht alle Läufe haben entschieden), `unanimous` (alle einig) oder `split` (uneinig).
* **Übereinstimmung auf der Befehlszeile:** je Lauf-Paar die prozentuale Übereinstimmung und Cohens Kappa (nur auf den Datensätzen, die **beide** Läufe bewertet haben); bei drei oder mehr Läufen zusätzlich Fleiss' Kappa über alle Läufe zusammen (nur auf den Datensätzen, die **alle** Läufe bewertet haben) und die Zahl der uneinigen Datensätze. Die Einstufung (schwach, mässig, gut, …) folgt Landis und Koch (1977).
* Nur Entscheidungen zählen (`INCLUDE`/`EXCLUDE`/`UNCERTAIN` mit Status `ok`); ein Datensatz, den ein Lauf noch nicht erreicht hat oder bei dem die Antwort fehlerhaft war, zählt nirgends als Uneinigkeit.
* Nichts im Projekt wird verändert; der Befehl braucht keine Sperre.

## 6n. Mehrere Modelle sind sich uneinig: `crapai adjudicate` und `crapai discuss`

Zusätzlich zum Vergleich (Abschnitt 6m) können Sie die Datensätze, bei denen sich die verglichenen Läufe **uneinig** waren, automatisch klären lassen - mit einem Schiedsrichter-Modell oder indem die ursprünglichen Modelle sich gegenseitig antworten. Beide Befehle ändern nichts an `records.csv`; das Ergebnis ist ein eigener, neuer Lauf (sichtbar in `crapai runs`, aber nicht in der Auswertung oder im Lauf-Vergleich, weil er nur die umstrittenen Datensätze enthält).

**Schiedsrichter (`crapai adjudicate`):** Ein zusätzliches Modell - die aktuell in `project.yaml` eingestellten `llm:`-Einstellungen - liest den Datensatz, die Kriterien und die Entscheidung samt Begründung **jedes** uneinigen Laufs und entscheidet einmal, selbst.

```powershell
crapai adjudicate mein-review --runs run-001,run-002
```

**Diskussion (`crapai discuss`):** Die ursprünglichen Modelle der verglichenen Läufe bekommen die Gegenmeinung zu lesen und dürfen ihre Entscheidung überdenken - bis zu `discussion.max_rounds` Runden (Standard 3). Jedes Modell wird dabei mit **seinen eigenen** Einstellungen aufgerufen (aus dem Manifest seines Laufs), nicht mit den aktuell in `project.yaml` eingestellten - sonst wäre es kein Gespräch zwischen verschiedenen Modellen.

```powershell
crapai discuss mein-review --runs run-001,run-002,run-003 --max-rounds 3 --tie-break majority
```

* `--runs id1,id2,...`: zwei oder mehr **verschiedene**, abgeschlossene Läufe (durch Komma getrennt); dieselbe Lauf-ID doppelt zu nennen wird abgelehnt (E203) statt stillschweigend "perfekte Übereinstimmung mit sich selbst" zu melden.
* `--max-rounds N` (nur `discuss`): überschreibt `discussion.max_rounds` für diesen Aufruf.
* `--tie-break majority|no_consensus` (nur `discuss`): überschreibt `discussion.tie_break`. `majority`: die Entscheidung, auf die sich die meisten Modelle festlegen, gewinnt; ein echtes Patt (z. B. 1 zu 1) gilt weiterhin als kein Konsens. `no_consensus`: nie einen Sieger küren, auch bei klarer Mehrheit.
* `--resume LAUF-ID`: einen unterbrochenen oder pausierten Schiedsrichter-/Diskussionslauf fortsetzen (wie bei `crapai screen --resume`); bereits geklärte Datensätze werden nicht erneut gesendet. `--runs` muss dieselben Läufe nennen (die Reihenfolge spielt dabei keine Rolle), sonst wird die Fortsetzung mit `E204` abgelehnt. Bei einer Pause oder Unterbrechung nennt die Ausgabe den genauen Befehl zum Fortsetzen.
* `--yes`: ohne Rückfrage starten (sonst wird die Anzahl der umstrittenen Datensätze angezeigt und nachgefragt, wie bei `crapai screen`).
* Wie bei jedem Modellaufruf: kann Geld kosten. Ein Datensatz, den (noch) nicht alle gewählten Läufe bewertet haben, zählt nicht als Uneinigkeit.
* Das Ergebnis trägt je Datensatz eine Entscheidung (`INCLUDE`/`EXCLUDE`/`UNCERTAIN`) und bei `discuss` zusätzlich, ob Konsens erreicht wurde, wie viele Runden gebraucht wurden und - ohne Konsens - `NO_CONSENSUS` oder die per Mehrheit gewählte Entscheidung samt der Entscheidungsregel, die gegriffen hat.

Rückgabecodes von `crapai adjudicate` und `crapai discuss` (dieselbe Bedeutung wie bei `crapai screen`, Abschnitt 6k):

| Code | Bedeutung |
|---|---|
| 0 | Lauf abgeschlossen, alle umstrittenen Datensätze geklärt |
| 4 | abgeschlossen, aber einzelne Datensätze mit Fehlern (`--resume` wiederholt genau diese) |
| 3 | pausiert oder unterbrochen; `--resume` setzt fort |
| 1 | Fehlschlag, den Sie beheben können (Schlüssel, Einstellungen, keine Rückfrage möglich) |
| 2 | Fehlschlag durch die Umgebung (Platte voll, Datei gesperrt, Projekt in Benutzung, unerwartet) |

## 6o. Volltext-Screening mit PDF-Dokumenten (ADR 0026)

Nach dem Titel-/Abstract-Screening (Abschnitt 6k) kann derselbe Befehl `crapai screen` auch den **Volltext** beurteilen - für die Datensätze, zu denen eine PDF importiert und zugeordnet wurde (Abschnitt 5.5).

### Ablauf

1. Titel-/Abstract-Screening wie gewohnt durchführen (Abschnitt 6k).
2. PDFs als ZIP importieren: `crapai import mein-review fulltexte.zip --label Volltexte` (Abschnitt 5.5). Jede PDF wird per DOI/Titel einem Datensatz zugeordnet; nur Datensätze mit einer **zugeordneten, lesbaren** PDF werden später zum Volltext-Screening zugelassen - alle anderen (keine PDF gefunden, oder eine gefundene PDF ist `NO_TEXT`/`ENCRYPTED`/`IMPORT_ERROR`) werden nicht angefragt, nicht stillschweigend übersprungen.
3. `project.yaml` auf den Volltext-Modus umstellen:

   ```yaml
   project:
     mode: fulltext                        # statt abstract
   screening:
     prompt_variant: structured_fulltext    # oder baseline_fulltext/gpt_improved_fulltext (legacy_xxx_yyy)
     output_format: structured              # muss zur gewählten Variante passen
     fulltext:
       strategy: truncate                   # truncate | sections (map_reduce: noch nicht umgesetzt, wird beim Start abgelehnt)
       repeat_criteria_after_text: false
   ```

4. `crapai screen mein-review` erneut ausführen - wie jeder Lauf, mit Kostenvoranschlag, Fortschrittsbalken, `--resume` usw. (Abschnitt 6k). Das Ergebnis trägt dieselbe `study_uid` wie der Titel-/Abstract-Datensatz, sodass die Auswertung (Abschnitt 6l) beide Entscheidungen nebeneinander zeigen kann.

### Die drei Strategien (`screening.fulltext.strategy`)

* **`truncate`** (Standard): Der Text wird auf das Kontextfenster des Modells gekürzt (mit Hinweis im Protokoll, wenn gekürzt wurde). Einfach, günstig, verliert alles nach dem Schnitt.
* **`sections`**: Nur die Abschnitte Methods/Results/Discussion werden geschickt (automatisch erkannt an Überschriftzeilen); ohne erkennbare Überschrift fällt die Software auf `truncate` zurück, statt nichts zu schicken.
* **`map_reduce`**: **Noch nicht umgesetzt.** Der Plan sieht vor, den Text in Abschnitte zu teilen, je Abschnitt Belege zu sammeln und am Ende zusammenzuführen (deutlich gründlicher, aber 20-40-fache Kosten eines Abstract-Laufs). `crapai screen` lehnt diese Einstellung beim Start klar ab (E203), statt sie falsch zu verarbeiten.

### Grenzen dieser Version

* Nur **ZIP-Import** von PDFs wird unterstützt, keine einzelnen PDF-Dateien (Abschnitt 5.5).
* Gescannte PDFs ohne Textlayer (`NO_TEXT`) werden nicht automatisch per OCR gelesen.
* Es gibt noch keinen Kostenvoranschlag, der die Volltext-Länge berücksichtigt; der allgemeine Kostenvoranschlag vor `crapai screen` gilt unverändert.

## 6j. Einstellungen ändern: `project.yaml`, Oberfläche, `crapai config`

Fast nichts ist im Programm fest verdrahtet: Schwellen, Grenzen und Annahmen sind Einstellungen. Es gibt drei Wege, sie zu ändern, die sich ergänzen:

1. **`project.yaml`** von Hand bearbeiten (mit Kommentaren, alle Einstellungen, Vorlage `templates/project.example.yaml`).
2. **Oberfläche, Seite Einstellungen:** ein Formular mit den wichtigsten Einstellungen (Duplikate, Vorfilter, Abstract-Qualität, Screening, Sprachmodell, Grenzen und Kosten). Die Änderungen werden geprüft und gespeichert; ungültige Werte werden abgelehnt und nichts wird geschrieben. „Alle Änderungen zurücksetzen“ macht sie rückgängig.
3. **Befehlszeile:**

```powershell
crapai config show mein-review              # alle Einstellungen mit Wert und Quelle
crapai config show mein-review --changed    # nur, was ausserhalb der project.yaml geändert wurde
crapai config set mein-review quality.short_abstract_words=30 limits.rpm=200
crapai config reset mein-review limits.rpm  # eine Einstellung zurück (ohne Namen: alle)
```

**Wohin werden Änderungen aus Oberfläche und `config set` geschrieben?** In die kleine Datei `project.overrides.yaml` neben der `project.yaml`. Ihre `project.yaml` mit allen Kommentaren bleibt unverändert. Die Datei ist maschinell verwaltet; löschen Sie sie (oder `crapai config reset`), sind wieder genau die Werte der `project.yaml` in Kraft.

**Rangfolge** (oben gewinnt): Befehlszeile, Umgebungsvariable (`CRAPAI_LLM__MODEL=gpt-4o` setzt `llm.model`), `project.overrides.yaml`, `project.yaml`, Benutzerdatei (`~/.config/crapai/config.yaml`), eingebaute Werte. `crapai config show` nennt je Wert die Quelle: *hier geändert*, *Umgebung*, *project.yaml*, *Benutzereinstellung* oder *Standard*.

**Wichtige Einstellungen**

| Einstellung | Standard | Bedeutung |
|---|---|---|
| `quality.short_abstract_words` | 40 | weniger Wörter: Hinweis „kurz“ (zwei Sätze deuten auf einen Fehler oder ein abgeschnittenes Abstract) |
| `quality.long_word_letters` | 40 | ein einzelnes Wort mit mehr Buchstaben sieht zusammengeklebt aus |
| `quality.garbled_mean_word_letters`, `quality.min_words_for_mean` | 9,0 / 30 | mittlere Wortlänge, ab der ein Abstract kaputt aussieht, und die Mindestzahl Wörter dafür |
| `quality.short_abstract_chars_unspaced` | 120 | wie „kurz“ für Chinesisch, Japanisch, Koreanisch, Thai (in Zeichen) |
| `preflight.min_abstract_ratio` | 0,60 | Quellen mit kleinerem Anteil an Abstracts erhalten eine Warnung |
| `dedup.min_title_words` | 4 | kürzere Titel gleichen nie allein über den Titel |
| `dedup.fuzzy.enabled`, `.threshold`, `.max_year_difference`, `.require_author_agreement` | aus, 0,94, 1, ja | unscharfe Duplikatsuche (Abschnitt 6a) |
| `limits.seconds_per_request`, `limits.cost_uncertainty`, `llm.expected_output_tokens` | 3 s, 0,15, 120 | Annahmen der Kosten- und Dauerschätzung |

Die Hinweise zur Abstract-Qualität sind **nur Hinweise**: Sie schliessen nie einen Datensatz aus. Falsch gesetzte Werte kosten deshalb nichts ausser einer Warnung.

## 6k. Das Screening: `crapai screen`

Dieser Befehl schickt die Datensätze, die nicht ausgeschlossen sind, **einzeln** an das Sprachmodell und speichert für jeden Datensatz einen Vorschlag (`INCLUDE`, `EXCLUDE` oder `UNCERTAIN`) mit Begründung. **Die Vorschläge ersetzen nie Ihre Entscheidung:** jeder Vorschlag wird von Menschen geprüft.

### Der Grundgedanke: nichts geht verloren

Ein Lauf mit 80'000 Datensätzen dauert Stunden. Irgendwann kann etwas schiefgehen: das Netz fällt aus, das Guthaben ist aufgebraucht, der Rechner geht in den Ruhezustand. Das Programm ist deshalb so gebaut, dass **jeder Abbruch bekannt, protokolliert und behebbar** ist:

* Jedes Ergebnis wird **sofort** an die Datei `screening.jsonl` angehängt und auf den Datenträger geschrieben. Bricht der Lauf bei 79'000 ab, sind die 79'000 Ergebnisse gespeichert.
* Die Datensätze werden in **Päckchen** (`run.batch_size`, Standard 1000) verarbeitet. Nach jedem Päckchen prüft das Programm **auf dem Datenträger**, ob für jeden Datensatz des Päckchens wirklich eine Ergebniszeile steht, zählt die Fehler, schreibt einen Zwischenstand und macht erst dann weiter. Ein Problem fällt so nach höchstens einem Päckchen auf.
* Jeder Halt hat einen **Zustand** und einen **Code** (siehe unten), steht im Protokoll und in der Datei `manifest.json` des Laufs.
* `crapai screen mein-review --resume` macht **genau dort weiter**: bereits erledigte Datensätze werden nicht noch einmal bezahlt, die restlichen (im Beispiel die letzten 1000) werden in einer neuen Sitzung abgeschlossen.
* Der **Fortschrittsbalken** ist immer sichtbar: Prozent, erledigte und gesamte Datensätze, Anzahl ok und Fehler, aktuelles Päckchen, bisherige Kosten, geschätzte Restzeit und die Zahl der gleichzeitigen Anfragen.

### Vorbereitung

1. Projekt anlegen, Dateien importieren, `crapai check mein-review` ausführen (Abschnitt 6b). Der Befehl `screen` aktualisiert Duplikate und Gültigkeit selbst noch einmal.
2. **Modell und Anbieter** in der `project.yaml` (oder im Formular der Oberfläche) einstellen:

   ```yaml
   llm:
     provider: openai_compatible           # SwissGPT, Azure, vLLM, LM Studio ...
     base_url: "https://<adresse-des-dienstes>/v1"
     model: "<modellname>"
     api_key_env: SWISSGPT_API_KEY         # NAME der Umgebungsvariable, nie der Schlüssel
   ```

   Für OpenAI selbst: `provider: openai`, `model: gpt-4o-mini`, `api_key_env: OPENAI_API_KEY` (ohne `base_url`). Der Anbieter `anthropic` ist in dieser Version noch nicht verfügbar (E203).
3. **Den Schlüssel setzen, ohne ihn irgendwo zu speichern**, in derselben Terminalsitzung, in der Sie `crapai` starten:

   ```powershell
   $env:SWISSGPT_API_KEY = "…"      # Windows PowerShell
   ```

   ```bash
   export SWISSGPT_API_KEY="…"      # macOS / Linux
   ```

   Der Schlüssel steht nie in einer Projektdatei, nie im Protokoll, nie in einer Fehlermeldung und nie in den Ergebnissen. Fehlt die Variable, bricht der Befehl **vor** dem ersten Versand mit E301 ab und nennt den Namen der Variable.
4. Das Paket für den Anbieter installieren: `pip install "crapai[llm-openai]"`.
5. **Erst klein testen:** `crapai screen mein-review --sample 20` zieht 20 zufällige Datensätze (mit `run.sample_seed` jedes Mal dieselben), kostet wenig und zeigt, ob Kriterien, Modell und Schlüssel stimmen. Ein Probelauf zählt **nicht** als Screening im PRISMA-Fluss.

### Der Befehl

```powershell
crapai screen mein-review                    # fragt nach und startet einen neuen Lauf
crapai screen mein-review --yes              # ohne Rückfrage (Skripte)
crapai screen mein-review --sample 20        # Probelauf mit 20 zufälligen Datensätzen
crapai screen mein-review --resume           # den neuesten unfertigen Lauf fortsetzen
crapai screen mein-review --resume --run-id 2026-10-01T14-05_run-003
crapai screen mein-review --resume --no-retry-failed   # fehlgeschlagene nicht erneut versuchen
crapai screen mein-review --no-progress      # ohne Fortschrittsbalken
crapai screen mein-review --json --yes       # Ergebnis als JSON auf stdout (Meldungen auf stderr)
crapai runs   mein-review                    # alle Läufe mit Zustand und Zahlen
crapai pause  mein-review                    # einen laufenden Lauf (anderes Terminal) pausieren
crapai stop   mein-review                    # einen laufenden Lauf stoppen (fortsetzbar)
```

Optionen von `screen`: `--sample K`, `--resume`, `--run-id`, `--retry-failed/--no-retry-failed`, `--yes`, `--no-progress`, `--json`, `--lang`. Die Optionen `pause` und `stop` nehmen `--run-id` und `--lang`, `runs` nimmt `--json` und `--lang`.

**Bestätigung:** Vor einem Lauf zeigt das Programm die geschätzten Kosten (Band und schlechtester Fall) und die geschätzte Dauer und fragt, ob es starten soll. Ohne Terminal und ohne `--yes` startet nichts (Rückgabecode 1). Liegt der schlechteste Fall über `limits.max_cost`, steht ein Hinweis da: der Lauf pausiert dann, sobald das Limit erreicht ist.

**Fortschrittsanzeige:** Auf dem Terminal wird eine Zeile laufend überschrieben:

```
[##########..........]  50 %  40'000/80'000  ok 39'950  errors 50  batch 41/80  cost 12.3400  ETA 2 h 10 min  parallel 5
```

Ohne Terminal (Umleitung in eine Datei, Planer) schreibt das Programm alle 30 Sekunden, bei jedem neuen Päckchen und am Ende eine normale Zeile. `--no-progress` schaltet die Anzeige ganz ab.

### Was ein Lauf tut

1. **Planen:** Die Datensätze ohne Ausschlussgrund (und mit Abstract, ausser `screening.include_title_only`) werden in `runs/<lauf-id>/plan.json` festgehalten. Bei `--resume` wird dieser Plan wiederverwendet, nicht neu berechnet.
2. **Sperre:** Das Projekt ist für andere Prozesse gesperrt (Abschnitt 6f); ein Herzschlag zeigt, dass der Lauf lebt.
3. **Je Datensatz:** Prompt bauen, Anfrage senden (mit den Regeln für Wiederholung, Wartezeit und Begrenzung unten), Antwort prüfen, Ergebniszeile schreiben.
4. **Je Päckchen:** auf der Platte prüfen, Fehlerquote bewerten, Zwischenstand (`manifest.json`) speichern.
5. **Ende:** Zustand und Ursache speichern; bei einem vollständigen, abgeschlossenen Lauf (kein Probelauf) ein Ereignis für den PRISMA-Fluss schreiben.

### Das Screening in der Oberfläche (Seite „Lauf“)

Die Seite **Lauf** der Oberfläche (Abschnitt 6h) macht dasselbe wie `crapai screen`, aber mit Bedienelementen:

* **Start:** Zusammenfassung der Einstellungen (Anbieter, Modell, Prompt, Päckchengrösse), Kosten- und Zeitschätzung, Feld „Probelauf“ (Anzahl zufälliger Datensätze, 0 = alle), ein Kontrollkästchen für das Einverständnis („die Datensätze werden an den Anbieter gesendet und können Geld kosten“) und die Schaltfläche *Lauf starten*. Ohne Häkchen ist die Schaltfläche gesperrt. Schlüssel, Einstellungen und Sperre werden **vor** dem Start geprüft; ein Fehler (E301 fehlender Schlüssel, E402 Projekt in Benutzung, E203 ungültige Einstellung) erscheint sofort auf der Seite und es wird nichts gestartet.
* **Der Schlüssel** muss in dem Terminal gesetzt sein, in dem `crapai ui` gestartet wurde (Umgebungsvariable, Abschnitt oben); die Seite nennt den Namen der Variable und speichert nie einen Schlüssel.
* **Der Lauf arbeitet in einem eigenen Prozess** (`python -m crapai screen …`), nicht in der Oberfläche. Schliessen Sie den Browser-Tab oder starten Sie die Oberfläche neu: der Lauf geht weiter, die Seite findet ihn über `manifest.json` wieder. Was der Prozess ausgibt, steht in `.crapai/screen.out` (die Seite zeigt es, falls ein Start scheitert).
* **Fortschritt:** Fortschrittsbalken mit „x von y Datensätzen (p %)“, Kacheln für ok, Fehler, Kosten und Päckchen, die Tabelle der Päckchen. Die Anzeige aktualisiert sich alle zwei Sekunden selbst.
* **Pausieren / Stoppen:** schreiben `control.json`; der Lauf beendet die Anfragen im Flug und hält im Zustand `paused` bzw. `interrupted`.
* **Nach dem Halt:** die Seite nennt Zustand, Ursache und Code (z. B. „E307 Guthaben aufgebraucht“), zeigt die Datensätze mit Fehlern und bietet *Diesen Lauf fortsetzen* an. Ein Lauf, dessen Zustand „läuft“ lautet, der aber seit 30 Sekunden nichts gespeichert hat, wird als **veraltet** gemeldet (Prozess beendet?): dann `crapai unlock` und fortsetzen.
* **Alle Läufe** stehen in einer Tabelle (Zustand, erledigt/gesamt, Fehler, Kosten).
* Ein ganz neuer Lauf nach einem unfertigen wird über die Befehlszeile gestartet (`crapai screen`), damit ein angefangener Lauf nicht versehentlich liegen bleibt.

### Die Zustände eines Laufs

| Zustand | Bedeutung | Fortsetzen? |
|---|---|---|
| `running` | der Lauf arbeitet (oder wurde hart beendet; siehe unten) | ja, nach Entfernen der Sperre |
| `paused` | bewusst oder durch eine Schutzregel angehalten | ja |
| `interrupted` | durch Strg+C, `crapai stop` oder einen Abbruch beendet | ja |
| `failed` | ein Problem, das erst behoben werden muss (z. B. Schlüssel) | ja, nach der Behebung |
| `completed` | alle Datensätze bearbeitet | nur um fehlgeschlagene Datensätze zu wiederholen |
| `canceled` | verworfen | nein |

### Wann hält ein Lauf an, und was tun?

| Ursache | Zustand | Code | Was tun |
|---|---|---|---|
| Strg+C (einmal), `crapai stop` | `interrupted` | | laufende Anfragen werden beendet (`run.stop_grace_seconds`), dann Halt; `--resume` |
| Strg+C ein zweites Mal | sofortiger Abbruch | | `--resume`; die Anfragen im Flug werden wiederholt |
| `crapai pause` | `paused` | | `--resume` |
| Schlüssel fehlt oder wird abgelehnt (401/403) | `failed` | E301 | Schlüssel und `llm.api_key_env` prüfen, dann `--resume` |
| Guthaben oder Kontingent aufgebraucht | `paused` | E307 | aufladen, dann `--resume` |
| Ergebnisse können nicht gespeichert werden (Platte voll, Datei gesperrt) | `failed` | E403 / E401 | Platz schaffen, Programme schliessen, `--resume` |
| mehr als `run.max_batch_error_rate` der Datensätze eines Päckchens sind fehlgeschlagen | `paused` | E308 | Protokoll lesen, Ursache beheben, `--resume` |
| `run.max_consecutive_errors` Fehler in Folge | `paused` | E308 | wie oben (meist Ausfall des Dienstes) |
| `limits.max_cost` erreicht | `paused` | E308 | Limit erhöhen (`crapai config set … limits.max_cost=…`), `--resume` |
| Projektsperre verloren | `failed` | E402 | anderen Prozess prüfen, `--resume` |
| Rechner aus, Prozess beendet (kein Halt durch das Programm) | `running` | | `crapai unlock`, dann `--resume` |

**Ein einzelner fehlgeschlagener Datensatz stoppt den Lauf nie.** Er erhält eine Ergebniszeile mit Status und Code und wird bei `--resume` erneut versucht.

### Fortsetzen: das Beispiel mit 80'000 Datensätzen

Der Lauf bricht bei 79'000 ab (Zustand `paused` oder `interrupted`). Sie sehen die Meldung mit Zustand, Ursache und Code, der Rückgabecode ist 3. Im Protokoll (`.crapai/app.log`) steht, was geschah. Dann:

```powershell
crapai runs mein-review                 # zeigt: paused, 79000/80000 erledigt
crapai screen mein-review --resume      # bearbeitet nur die restlichen 1000 (+ fehlgeschlagene)
```

Die Ergebnisse der 79'000 bleiben unberührt; `screening.jsonl` bekommt nur neue Zeilen. **Gilt eine Ergebniszeile als letzte zu einem Datensatz, dann zählt sie** (frühere Fehlerzeilen bleiben als Verlauf erhalten). War der Prozess hart beendet (Stromausfall, Task-Manager), bleibt die Projektsperre stehen: `crapai unlock mein-review` entfernt sie, sobald der Prozess nicht mehr läuft (Abschnitt 6f); ein halb geschriebene letzte Zeile der Ergebnisdatei wird dabei erkannt und abgeschnitten.

**Fortsetzen nur mit unveränderten Einstellungen:** Was die Antworten prägt (Anbieter, Modell, `base_url`, Temperatur, `top_p`, `seed`, `max_output_tokens`, Prompt-Variante und Wortlaut, Kriterien, Ziele, Antwortformat, Sprache der Begründung) wird beim Start als Fingerabdruck gespeichert. Hat sich etwas davon geändert, lehnt `--resume` mit **E204** ab und nennt die Unterschiede, denn sonst wären die Ergebnisse eines Laufs nicht vergleichbar. Stellen Sie die alten Werte wieder her oder starten Sie einen neuen Lauf. Einstellungen, die nur das Tempo und den Schutz betreffen (`run.*`, `limits.*`), dürfen Sie zwischen den Sitzungen ändern.

### Die Dateien eines Laufs

`runs/<lauf-id>/` (die Kennung hat die Form `2026-10-01T14-05_run-003`):

| Datei | Inhalt |
|---|---|
| `manifest.json` | Zustand, Zahlen, Kosten, Päckchen-Tabelle, Fingerabdrücke (Kriterien, Einstellungen, Prompt), Sitzungen, Warnungen, letzter Fehler; wird atomar ersetzt und während des Laufs alle `run.checkpoint_seconds` gespeichert |
| `screening.jsonl` | eine Zeile je Ergebnis, **nur anhängen**; die letzte Zeile je Datensatz gilt |
| `plan.json` | die geplanten Datensätze (Reihenfolge und Auswahl) |
| `control.json` | ein Auftrag von aussen (`pause` oder `stop`), wird vom Lauf jede Sekunde gelesen und danach gelöscht |

Eine **beschädigte Zeile in der Mitte** von `screening.jsonl` ist ein Fehler (E404), den das Programm nicht stillschweigend überspringt; eine beschädigte **letzte** Zeile (Abbruch beim Schreiben) wird ignoriert und vor dem nächsten Anhängen abgeschnitten.

### Das Ergebnis je Datensatz

| Status | Bedeutung |
|---|---|
| `ok` | gültige Antwort; Felder `decision`, `reasoning`, Urteile je Kriterium, Zitate |
| `parse_error` | die Antwort war nicht lesbar oder ungültig (auch nach `limits.max_parse_retries` Nachfragen); **nie** ein stillschweigender Einschluss |
| `api_error` | der Dienst antwortete nicht (nach `limits.max_retries` Wiederholungen) oder verweigerte den Inhalt (E306) |
| `truncated` | die Antwort wurde abgeschnitten, auch mit doppeltem Limit |
| `too_long` | der Datensatz passt nicht in das Kontextfenster (`llm.context_tokens`), er wird nicht gesendet |

Zusätzliche **Markierungen** (`flags`) zu einem `ok`-Ergebnis: `inconsistent` (die Entscheidung widerspricht den eigenen Urteilen des Modells: nicht korrigiert, sondern zur Prüfung markiert), `quote_unverified` (ein Zitat steht nicht im Datensatz), `model_changed` (der Anbieter meldete einen anderen Modellnamen), `length_retry`, `parse_retry`.

**Das Antwortformat:** Das Modell antwortet mit einem JSON-Objekt: Urteile je Einschluss- und Ausschlusskriterium (`met`/`not_met`/`unclear` bzw. `triggered`/`not_triggered`/`unclear`), Unklarheiten, Begründung, und **zuletzt** die Entscheidung. Das Programm prüft die Antwort selbst (SwissGPT kennt kein festes Antwortschema) und leitet die Entscheidung zur Gegenprobe aus den Urteilen ab. Das alte Format (letzte Zeile `XXX` = ausschliessen, `YYY` = einschliessen) bleibt mit `screening.output_format: legacy_xxx_yyy` möglich.

**Schutz vor eingeschleusten Anweisungen:** Der Datensatz steht zwischen `<record>`-Marken und der Systemtext weist an, alles darin als Daten zu behandeln. Antwortet das Modell trotzdem ungültig (etwa „Ich denke, einschliessen“), ist das ein `parse_error` und kein Einschluss.

### Tempo und Schutz: die Einstellungen

Alle Werte sind Einstellungen (Abschnitt 6j), im Formular der Oberfläche (Abschnitte *Screening-Lauf*, *Grenzen und Kosten*, *Sprachmodell*) oder mit `crapai config set`:

| Einstellung | Standard | Bedeutung |
|---|---|---|
| `run.batch_size` | 1000 | Datensätze je Päckchen; nach jedem Päckchen wird geprüft |
| `run.max_batch_error_rate` | 0,5 | Pause, wenn mehr als dieser Anteil eines Päckchens fehlschlug (Päckchen unter 5 Datensätzen werden nicht nach Quote beurteilt) |
| `run.max_consecutive_errors` | 20 | Pause nach so vielen Fehlern in Folge (0 = aus) |
| `run.retry_failed_on_resume` | ja | fehlgeschlagene Datensätze bei `--resume` erneut versuchen |
| `run.checkpoint_seconds`, `run.heartbeat_seconds` | 2, 10 | Speichern des Zwischenstands, Lebenszeichen der Sperre |
| `run.stop_grace_seconds` | 10 | Nachfrist für laufende Anfragen nach einem Stopp |
| `run.sample_seed` | 42 | Zufallszahl für `--sample` |
| `run.retry_base_delay_s`, `run.retry_max_delay_s`, `run.max_retry_time_s` | 1, 60, 600 | Wartezeiten bei Wiederholungen |
| `limits.max_concurrency` | 5 | gleichzeitige Anfragen (sinkt bei Überlastmeldungen automatisch und steigt wieder) |
| `limits.rpm`, `limits.tpm` | 500, 200'000 | Anfragen und Tokens je Minute, vom Programm eingehalten |
| `limits.max_retries`, `limits.max_parse_retries` | 5, 2 | Wiederholungen bei Serverfehlern / Nachfragen bei ungültigen Antworten |
| `limits.max_cost` | 10 | Pause vor Überschreiten dieser Summe (`null` = kein Limit) |
| `llm.timeout_s`, `llm.max_output_tokens`, `llm.context_tokens` | 60, 800, leer | Frist je Anfrage, Antwortlimit, Kontextfenster |

**Wiederholungen:** Serverfehler, Zeitüberschreitung und Verbindungsabbruch (E305) werden mit wachsender Wartezeit wiederholt. Bei „zu viele Anfragen“ (E302) wartet das Programm die vom Dienst genannte Zeit ab und halbiert die Parallelität. Schlüsselfehler (E301), aufgebrauchtes Guthaben (E307), zu langer Text (E303) und verweigerter Inhalt (E306) werden **nicht** wiederholt.

### Testen ohne Kosten: der Mock-Anbieter

Mit `llm.provider: mock` läuft alles ohne Netz und ohne Schlüssel; `llm.model` wählt das Szenario `S1` bis `S15` (S1: alles gelingt; S2: Überlastmeldungen; S3: jeder siebte Aufruf scheitert; S4: ein Viertel der Datensätze läuft in die Zeitüberschreitung; S5: kaputtes JSON; S7: Schlüssel abgelehnt; S14: Guthaben aufgebraucht; die übrigen siehe `docs/ENTWICKLERDOKUMENTATION.md`). So können Sie Abbrüche und das Fortsetzen gefahrlos üben.

### Rückgabecodes von `crapai screen`

| Code | Bedeutung |
|---|---|
| 0 | Lauf abgeschlossen, alle Datensätze `ok` |
| 4 | abgeschlossen, aber einzelne Datensätze mit Fehlern (`--resume` wiederholt genau diese) |
| 3 | pausiert oder unterbrochen; `--resume` setzt fort |
| 1 | Fehlschlag, den Sie beheben können (Schlüssel, Einstellungen, keine Rückfrage möglich) |
| 2 | Fehlschlag durch die Umgebung (Platte voll, Datei gesperrt, Projekt in Benutzung, unerwartet) |

## 6i. Protokoll und Fehlersuche

Jedes Projekt hat ein Protokoll `.crapai/app.log` (rotierend, 1 MB, drei ältere Dateien). Jede Zeile hat Zeit, Stufe, eine **Sitzungskennung** (eine je Programmstart, damit sich die Zeilen einer Sitzung finden lassen), den Namen des Programmteils und die Meldung. Titel, Abstracts und Schlüssel stehen nie im Protokoll; Zeichenfolgen, die wie ein Schlüssel oder Token aussehen, werden zusätzlich durch `***` ersetzt.

* `crapai --verbose …` (oder `-v`) zeigt zusätzlich die Protokollzeilen auf dem Bildschirm (stderr) und schreibt auch die Stufe DEBUG in die Datei. Die Option steht **vor** dem Befehl, zum Beispiel `crapai --verbose check mein-review`.
* Die Stufe lässt sich auch mit der Umgebungsvariable `CRAPAI_LOG_LEVEL` setzen (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Ein unbekannter Wert ergibt `INFO`.
* Kann die Protokolldatei nicht geöffnet werden (schreibgeschützter Ordner), läuft der Befehl trotzdem und meldet es einmal.
* In der Oberfläche zeigt die Seite Hilfe die letzten 200 Zeilen.

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

## 6e. Vorfilter: Sprache, Jahr, Publikationstyp, Stichwörter

Manche Kriterien sind Metadaten, die das Sprachmodell nicht zuverlässig beurteilt (zum Beispiel die Sprache einer Studie). Sie prüfen diese im Programm, **vor** dem Modell und ohne Kosten. Die Einstellung steht in der `project.yaml`:

```yaml
prefilters:
  language: { allow: [eng, ger], on_missing: pass }
  year: { min: 2015, max: null, on_missing: pass }
  publication_types: { exclude: [Editorial, Letter, Comment], on_missing: pass }
  keywords: { include_any: [], exclude_any: [animal model, in vitro], case_sensitive: false, on_missing: pass }
  exclude_retracted: true
```

* Die Filter laufen automatisch bei `crapai check` (nach den Duplikaten, vor der Gültigkeitsprüfung). Datensätze, die durchfallen, werden **markiert, nicht gelöscht**: `PREFILTER_LANGUAGE`, `PREFILTER_YEAR`, `PREFILTER_TYPE`, `PREFILTER_KEYWORD` (Tabelle in 7a); `exclusion_details` sagt genau warum, zum Beispiel `language: fre (allowed: eng, ger)`.
* **Fehlende Angaben:** Fehlt Sprache, Jahr, Typ oder (bei den Stichwörtern) der ganze Text, gilt `on_missing`. Mit `pass` (Standard) geht der Datensatz ans Modell, damit nichts wegen fehlender Daten verloren geht; mit `exclude` wird er markiert. Ein Sprachtext wie "n/a" zählt als fehlend.
* **Sprache:** `de`, `deu`, `ger` und `German` sind dasselbe, ebenso `en-US` und `en_GB` für Englisch. Hat ein Datensatz mehrere Sprachen ("eng; fre"), genügt eine erlaubte. Die Marken `und` (unbestimmt), `mul` (mehrere), `zxx`, `unk`, `nan` sagen nichts über die Sprache und zählen als fehlend.
* **Jahr:** Grenzen gelten einschliesslich; `null` heisst offen.
* **Publikationstyp:** Ein Datensatz wird ausgeschlossen, wenn irgendeiner seiner Typen in der Liste steht (Gross-/Kleinschreibung egal). Steht `Editorial` in der Liste, verfällt auch "Journal Article; Editorial".
* **Stichwörter (optional, standardmässig aus):** durchsucht Titel, Abstract und die Felder `keywords`/`keywords_mesh` als einen Text (Teilwort-Suche, standardmässig ohne Gross-/Kleinschreibung; `case_sensitive: true` schaltet das ab). `exclude_any`: ein Treffer schliesst aus. `include_any`: der Datensatz wird ausgeschlossen, wenn **keines** der Wörter vorkommt (eine Positivliste, wie bei der Sprache). Beide leer = Filter aus; sind beide gesetzt, hat `exclude_any` Vorrang. Die Oberfläche (Seite Einstellungen) bietet `include_any`/`exclude_any` als Listenfelder; `case_sensitive` wird nur in `project.yaml` eingestellt.
* Ändern Sie eine Einstellung, berechnet der nächste `crapai check` alles neu; alte Markierungen verschwinden, wenn sie nicht mehr zutreffen.
* Im PRISMA-Fluss zählen diese Datensätze (und ausgeschlossene zurückgezogene Studien) unter "vor dem Screening aus anderen Gründen entfernt" (Abschnitt 6d).

Unabhängig vom Vorfilter kann das Modell die Stichwörter zusätzlich als Kontext sehen (`screening.include_keywords_in_prompt: true`, Standard `false`): Title, Abstract **und** Keywords gehen dann in den Prompt. Das schliesst allein nichts aus - das Modell entscheidet weiterhin selbst; für einen harten, kostenlosen Ausschluss den Vorfilter oben verwenden. Beide Schalter sind unabhängig voneinander und lassen sich kombinieren.

## 6d. Ereignisse und PRISMA-Zahlen

Jeder Import, jede Duplikat-Markierung und jede Gültigkeitsprüfung schreibt eine Zeile in `data/events.jsonl` (was, wann, wie viele). Daraus berechnet das Programm die Zahlen des PRISMA-2020-Flussdiagramms: gefundene Datensätze je Quelle, entfernte Duplikate, vor dem Screening aus anderen Gründen Entfernte, Datensätze zum Screening. Die Datei wird nie umgeschrieben; löschen Sie sie nicht von Hand.

* **Wiederholtes `crapai dedup` zählt nichts doppelt**: pro Quelle gilt der letzte Stand.
* **Zwei Arten, Duplikate zu berichten** (`dedup.reporting_mode` in der `project.yaml`): `all_before_screening` zählt alle Duplikate als "Duplikate entfernt"; `between_databases_only` zählt nur die zwischen verschiedenen Quellen, Duplikate innerhalb einer Quelle erscheinen unter "vor dem Screening aus anderen Gründen entfernt". Die Summe stimmt in beiden Fällen.
* Fehlt ein Ereignis (zum Beispiel weil die Platte voll war), bleibt die Arbeit gültig; `crapai import`, `dedup` und `check` melden das mit einer Warnung (Rückgabecode 4). Führen Sie `crapai check` später erneut aus.
* **Veraltete Zahlen werden gemeldet, nicht verschwiegen.** Importieren Sie nach dem letzten `dedup`, erscheint `STALE_DEDUP`: Die neuen Datensätze zählen dann als "zum Screening" und nicht als Duplikate, bis Sie `crapai check` ausführen. Läuft `dedup` allein nach Vorfilter oder Gültigkeitsprüfung, werden deren ältere Zahlen nicht abgezogen (`STALE_PREFILTER`, `STALE_VALIDITY`), damit nichts doppelt gezählt wird.
* Wiederholtes `crapai check` schreibt nichts Neues, wenn sich nichts geändert hat; die Datei wächst nicht.
* Die Zahlen lassen sich als Datei ausgeben (`crapai export mein-review --what flow`, Abschnitt 6l) → `prisma_flow.json`. Nur die Grafik (PNG/SVG) folgt noch.

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
| `PREFILTER_KEYWORD` | Titel/Abstract/Keywords enthalten ein Wort aus `prefilters.keywords.exclude_any`, oder keines aus `include_any` (Abschnitt 6e) | Vorfilter |
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
| E405 | `init`: der Ordner ist schon ein Projekt oder nicht leer | Projekt öffnen oder neuen bzw. leeren Ordner wählen |
| E204 | `--resume`: Einstellungen haben sich seit dem Start des Laufs geändert | alte Werte wiederherstellen oder neuen Lauf starten (Abschnitt 6k) |
| E301 | Schlüssel fehlt oder wird vom Anbieter abgelehnt | Umgebungsvariable (`llm.api_key_env`) setzen bzw. Schlüssel prüfen; der Lauf wird `failed` |
| E302 | Anbieter meldet „zu viele Anfragen“ | automatisch: Wartezeit, geringere Parallelität; ggf. `limits.rpm` senken |
| E303 | Datensatz länger als das Kontextfenster | Status `too_long`; Datensatz von Hand prüfen oder `llm.context_tokens` korrigieren |
| E304 | Antwort des Modells unlesbar, ungültig oder abgeschnitten | Status `parse_error`/`truncated`; `--resume` versucht es erneut |
| E305 | Anbieter nicht erreichbar, Zeitüberschreitung, Serverfehler | automatische Wiederholung; danach Status `api_error` |
| E306 | Anbieter verweigert den Inhalt (Sicherheitsfilter) | Datensatz von Hand prüfen |
| E307 | Guthaben oder Kontingent aufgebraucht | aufladen, dann `--resume`; der Lauf ist `paused` |
| E308 | Schutzregel hat den Lauf pausiert (Fehlerquote, Fehler in Folge, Kostenlimit) | Protokoll lesen, Ursache beheben oder Limit anheben, dann `--resume` |
| E999 | unerwarteter Fehler | `.crapai/app.log` ansehen und den Fehler melden |

Weitere Codes (E202, E501/E502 Statistik) betreffen Funktionen, die noch folgen.

## 9. Häufige Fragen

**Kann ich dieselbe Datei aus zwei Datenbanken importieren?** Ja, wenn die Dateien verschieden sind. Doppelte Datensätze markieren Sie mit `crapai dedup` (Abschnitt 6a); sie werden nie gelöscht.

**Ich habe die falsche Datei importiert.** Die Originale in `sources/` und die Sicherungen in `data/.backup/` bleiben erhalten. Einen Import rückgängig machen
kann die Software noch nicht; legen Sie in diesem Fall ein neues Projekt an. *(Eine Funktion dafür ist nicht geplant.)*

**Die Umlaute sehen falsch aus.** Bei CSV-Dateien `--encoding cp1252` angeben. `records.csv` ist immer UTF-8.

**Warum sind Angaben in `extra_json`?** Damit nichts verloren geht, auch wenn es keine eigene Spalte gibt.

**Muss ich online sein?** Für Import, Prüfung und Export nicht. Nur `crapai screen` ruft den Modellanbieter auf (ausser mit dem Mock-Anbieter, Abschnitt 6k).

**Werden meine Daten an Dritte gesendet?** Der Import sendet nichts. Beim Screening gehen Titel und Abstracts an den von Ihnen gewählten Anbieter; das müssen Sie vorher
bestätigen (Rückfrage oder `--yes`). Es gibt keine Telemetrie.

## 10. Was noch kommt

Der PRISMA-Fluss als Grafik (PNG/SVG) und der Vergleich mit menschlichen Entscheidungen. Den Stand finden Sie in
`docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`; die Änderungen je Version in `CHANGELOG.md`.
