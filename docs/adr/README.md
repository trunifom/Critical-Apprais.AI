# Architecture Decision Records

Kurze Entscheidungsprotokolle. Neue Datei `NNNN-titel.md` mit *Entscheidung / Alternativen / Folgen*, wenn eine strukturelle Entscheidung fällt. Bezug: `docs/PROJEKTPLAN.md` Kap. 28.13.

- 0001 - Projektordner statt Datenbank
- 0002 - CSV und JSONL als kanonische Formate, XLSX nur Export
- 0003 - Append-only-Checkpoint
- 0004 - asyncio mit Semaphor und Token-Bucket
- 0005 - Strukturierte Antworten (JSON-Schema)
- 0006 - UI und Worker als getrennte Prozesse
- 0007 - Pydantic v2 und YAML für Konfiguration
- 0008 - Neues Repository, Module kopieren statt Fork
- 0009 - pyproject.toml mit Extras und Lockfile
- 0010 - Keine Telemetrie, keine Konten
- 0011 - Schlüssel nur per Umgebung oder OS-Schlüsselbund
- 0012 - Fehlercodes und i18n-Schlüssel je Fehler
- 0013 - GUI-Framework Streamlit
- 0014 - SwissGPT als voraussichtlicher Hauptanbieter
- 0015 - Volltext-Screening nicht in Version 1
- 0016 - Lizenz des Codes: PolyForm Noncommercial 1.0.0
- 0017 - Technische Namen: Kurzform CrAp-AI, Paket und Befehl `crapai`
- 0018 - Markieren statt Löschen: Ausschlussgründe, Reihenfolge, Vorsicht bei Duplikaten
- 0019 - Deterministische Vorfilter: Reihenfolge, Gründe, fehlende Metadaten
- 0020 - Ergebnisse der Gesamtprüfung: Sperre, Ereignisse, Dedup, Fehlerbehandlung
- 0021 - Einstellungen statt fester Zahlen, Überschreibdatei, unscharfe Duplikate ohne Zusatzpaket
- 0022 - Screening-Kern: Päckchen, Prüfung auf der Platte, Zustände, Fortsetzen
