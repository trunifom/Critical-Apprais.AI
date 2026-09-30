# CHANGELOG

Alle wesentlichen Änderungen an Critical Apprais.AI. Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung folgt [SemVer](https://semver.org/lang/de/); solange die Hauptversion 0 ist, können sich Schnittstellen ändern.
Änderungen an persistierten Namen (Spalten, Enum-Werte, Dateinamen) werden hier immer ausdrücklich genannt (Datenvertrag).
Jeder Eintrag verweist auf die Aufgabenkarte; die genauen Commits stehen in `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`.

## [Unveröffentlicht] - 0.0.1

### Hinzugefügt

* **Grundlagen (M0):** Lint-Konfiguration (`reference/` ausgenommen), Schichtentest für den Kern (ohne GUI-, CLI- und LLM-Importe), CI-Workflow für Windows/Linux/macOS und Python 3.11-3.13 (T-M0-02).
* **Paketskelett** mit den Unterpaketen `project, io, prisma, screening, llm, prompts, stats, services` (T-M1-01).
* **Fehlerhierarchie** `SaraError` mit Fehlercodes des Katalogs (T-M1-02).
* **Konfiguration `project.yaml`:** geprüfte Modelle (kein API-Schlüssel speicherbar, unbekannte Einstellungen werden abgelehnt, Fehler mit Pfad und Grund, `E201`/`E203`),
  Rangfolge CLI > Umgebung (`SARA_ABSCHNITT__SCHLUESSEL`) > Projekt > Benutzer > Standard (T-M1-02).
* **Projektordner:** atomares Schreiben mit Wiederholung und Ausweichdatei, Sperre mit Herzschlag und Übernahme veralteter Sperren, Ordnerstruktur mit Schema-Version, Warnung bei OneDrive/Dropbox/SharePoint (T-M1-03).
* **Formaterkennung** nach Inhalt (RIS, NBIB, BibTeX, CSV/TSV, XLSX, ZIP, PDF), mit Konfidenz und Begründung (T-M1-04).
* **Reader:** RIS (behebt den Vorgängerfehler L15: Fortsetzungszeilen gingen verloren) (T-M1-05), NBIB/MEDLINE (T-M1-06), BibTeX (tolerant, auch Cochrane-Exporte; 11,5-MB-Datei in etwa 1,5 s) (T-M1-07),
  Tabellen CSV/TSV/XLSX mit Aliasnamen, `--map` und Kodierungserkennung (T-M1-08).
* **Normalisierung und `records.csv`:** 40 Spalten nach Datenvertrag, DOI/Jahr/Listen/Text bereinigt, `EMPTY_RECORD` markiert, Restfelder verlustfrei in `extra_json`,
  verlustfreie Rundreise (Eigenschaftstest), Sicherungen in `data/.backup/`, Import-Protokoll mit SHA-256 und Erkennung erneuter Importe (`E106`) (T-M1-10).
* **Befehle** `sara init`, `sara import`, `sara status` mit Rückgabecodes 0/1/2/4, `--json`, `--lang` (T-M1-11); Import-Dienst und Projektdienst; Vorlagen `blank` und `demo`.
* **Texte** Deutsch und Englisch für Befehlszeile, Oberfläche und alle Fehlercodes (Was ist passiert - Warum - Was tun), Paritätstest (T-M1-12).
* **Dokumentation:** Benutzerhandbuch, Entwicklerdokumentation, Architektur, ausführliches README, dieses Änderungsprotokoll, Umsetzungsplan mit Fortschrittsliste.

### Geändert

* Die aus dem Vorgänger übernommenen Texte wurden angepasst: kein Volltext-Modus in Version 1, PIRD als Rahmenwerk, keine E-Mail- und Hintergrund-Worker-Texte (T-M1-12).

### Behoben

* Eine in Excel geöffnete `records.csv` liess den Import zuvor scheinbar gelingen und legte eine Nebendatei an; jetzt bricht der Import mit `E401` ab, ohne etwas zu verändern.

### Bekannte Einschränkungen

* Kein Screening, keine Duplikaterkennung, keine grafische Oberfläche (siehe Umsetzungsplan).
* `import.mappings` aus Plan Kap. 25.5 steht noch nicht in `project.yaml`; die Spaltenzuordnung liegt im Import-Protokoll.
* Technische Namen (`saralocal`, `sara`, `.sara/`) sind vorläufig (T-M0-03); die Lizenz des Codes ist offen (T-M0-01).
* Die CI-Matrix ist noch nicht auf GitHub gelaufen.
