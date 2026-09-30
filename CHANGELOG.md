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
  Rangfolge CLI > Umgebung (`CRAPAI_ABSCHNITT__SCHLUESSEL`) > Projekt > Benutzer > Standard (T-M1-02).
* **Projektordner:** atomares Schreiben mit Wiederholung und Ausweichdatei, Sperre mit Herzschlag und Übernahme veralteter Sperren, Ordnerstruktur mit Schema-Version, Warnung bei OneDrive/Dropbox/SharePoint (T-M1-03).
* **Formaterkennung** nach Inhalt (RIS, NBIB, BibTeX, CSV/TSV, XLSX, ZIP, PDF), mit Konfidenz und Begründung (T-M1-04).
* **Reader:** RIS (behebt den Vorgängerfehler L15: Fortsetzungszeilen gingen verloren) (T-M1-05), NBIB/MEDLINE (T-M1-06), BibTeX (tolerant, auch Cochrane-Exporte; 11,5-MB-Datei in etwa 1,5 s) (T-M1-07),
  Tabellen CSV/TSV/XLSX mit Aliasnamen, `--map` und Kodierungserkennung (T-M1-08).
* **Normalisierung und `records.csv`:** 40 Spalten nach Datenvertrag, DOI/Jahr/Listen/Text bereinigt, `EMPTY_RECORD` markiert, Restfelder verlustfrei in `extra_json`,
  verlustfreie Rundreise (Eigenschaftstest), Sicherungen in `data/.backup/`, Import-Protokoll mit SHA-256 und Erkennung erneuter Importe (`E106`) (T-M1-10).
* **Befehle** `crapai init`, `crapai import`, `crapai status` mit Rückgabecodes 0/1/2/4, `--json`, `--lang` (T-M1-11); Import-Dienst und Projektdienst; Vorlagen `blank` und `demo`.
* **Texte** Deutsch und Englisch für Befehlszeile, Oberfläche und alle Fehlercodes (Was ist passiert - Warum - Was tun), Paritätstest (T-M1-12).
* **Preflight** (T-M2-04): `crapai check` (Dedup + Gültigkeit, dann Bericht mit Status, Zahlen je Quelle, Gründen und Hinweisen; Rückgabecode 0/4/1; `--read-only`, `--json`) und `check_file` zur Prüfung einer Datei vor dem Import. Ohne Streamlit-Typen, nur Pfade. Die Konfigurationsmeldung nennt jetzt Pfad und Grund des ersten Problems (`crapai status` ebenso).
* **Gültigkeitsprüfung** (T-M2-03, Bausteine `prisma/validity.py`, `services/validity.py`): `NO_ABSTRACT`, `NOT_SCREENABLE` (Front-Matter), `RETRACTED` (optional), `abstract_quality`; gemeinsamer Katalog `prisma/reasons.py`, Duplikate ersetzen Gültigkeitsgründe (ADR 0018). Der Befehl `crapai check` folgt mit T-M2-04.
* **Wiederholbarer Tabellenimport:** `import.mappings` in der `project.yaml` (je Dateiname), Vorrang von `--map`; die Ausgabe nennt die Herkunft der Zuordnung.
* **Duplikate markieren** (`crapai dedup`, T-M2-01): vier Strategien, normalisierte Titel, nicht löschend, behält den vollständigsten Datensatz, im Zweifel keine Markierung, wiederholbar; Statistik innerhalb/zwischen Quellen. `dedup_method` erhält den Wert `pmid` (zu bestätigen).
* **Tests:** Abdeckungsmessung mit Zweigabdeckung (96 % gesamt, neuer Code 99-100 %), `tests/unit/test_edge_cases.py` (37 Randfälle), Wächtertest für Docstrings und Rückgabetypen der öffentlichen API.
* **Lizenz:** PolyForm Noncommercial 1.0.0 (`LICENSE`, ADR 0016, `license` in `pyproject.toml`): nicht kommerzielle Nutzung erlaubt, kommerzielle ausgeschlossen (T-M0-01).
* **Dokumentation:** Benutzerhandbuch, Entwicklerdokumentation, Architektur, ausführliches README, dieses Änderungsprotokoll, Umsetzungsplan mit Fortschrittsliste.

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
