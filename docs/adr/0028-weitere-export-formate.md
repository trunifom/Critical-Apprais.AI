# ADR 0028: Drei zusätzliche Export-Formate

Status: Angenommen als Umsetzungsentscheid des Agenten (2026-10-02); dritter und letzter Teil des Auftrags der Projektleitung (nach ADR 0026 Volltext-Screening und ADR 0027 Settings-Profile)

## Ausgangslage

Die Projektleitung wünschte drei Ergänzungen zu `crapai export`: BibTeX/NBIB-Export (symmetrisch zum Import), den PRISMA-Fluss als Grafik statt nur als Zahlen-JSON, und einen lesbaren Zusammenfassungsbericht für Publikationen/Anträge. Kein Plankapitel deckt dies ab.

## Entscheidung

1. **BibTeX/NBIB-Export** (`io/writers/bibtex.py`, `io/writers/nbib.py`): symmetrisch zu den bestehenden Lesern, nach dem Muster des RIS-Schreibers (`record_type` → Format-Typ über die `RECORD_TYPES`-Tabelle des jeweiligen Lesers, wiederverwendet statt verdoppelt). RIS und BibTeX tragen Screening-Vermerke (Ausschlussgrund, Duplikat, Rückzug) im Notizfeld; **NBIB bewusst nicht** - MEDLINE hat kein passendes freies Textfeld dafür, und ein erfundenes Tag würde nicht durch echte MEDLINE-Werkzeuge hindurch funktionieren. Bekannte, dokumentierte Einschränkung: Ein NBIB-Export ganz ohne PMID (keine Zeile trägt eine) kann vom eigenen NBIB-Leser nicht zurückgelesen werden, weil dessen Erkennung PMID als Signal braucht - eine Eigenschaft des Formats, kein Fehler dieses Programms.
2. **PRISMA-Fluss als Bild** (`io/writers/prisma_image.py`): Kästen-Pfeil-Diagramm (Identifiziert → Duplikate entfernt → Gescreent → Ausgeschlossen → [Volltext geprüft → Ausgeschlossen, nur wenn Volltext-Screening stattfand, ADR 0026] → Eingeschlossen), aus denselben Zahlen wie der bestehende JSON-Export. Nutzt `matplotlib`s objektorientierte Schnittstelle (`Figure`/`FigureCanvasAgg`) direkt, nie `pyplot` - ein Befehlszeilenprogramm darf nicht von `pyplot`s globalem, prozessweitem "aktuelle Abbildung"-Zustand abhängen. `matplotlib` war bereits eine bestehende, deklarierte (bisher ungenutzte) Abhängigkeit im Extra `stats` - keine neue Abhängigkeit nötig.
3. **DOCX-Zusammenfassungsbericht** (`io/writers/docx_report.py`): Ziele, Kriterien, PRISMA-Fluss-Tabelle und Screening-Ergebnisse des neusten abgeschlossenen Laufs (falls vorhanden; sonst ein sichtbarer Hinweis statt eines Fehlers) - nichts Neues berechnet, nur bereits vorhandene Werte (`ProjectConfig`, `PrismaFlow`, `stats.results.Analysis`). Braucht `python-docx`, **neue Abhängigkeit, von der Projektleitung im Chat freigegeben** (neues Extra `report`, analog zu `stats`/`import`/`llm-openai`: fehlt das Paket, klare Meldung E203 statt Absturz).

## Folgen

* `services/export.py`: `RECORD_FORMATS` um `bibtex`/`nbib` erweitert (Dateiendung `.bib` für `bibtex`, sonst entspricht die Endung dem Formatnamen); `export_flow()` bekommt `fmt` (`json`, Standard, oder `png`/`svg`); neue Funktion `export_report()`.
* `cli.py`: `--format` akzeptiert die neuen Werte; `--what flow`s bisheriger Standard `csv` wird weiterhin als `json` verstanden (keine Änderung für bestehende Skripte ohne `--format`); neuer Wert `--what report`.
* Oberfläche (Export-Seite): Formatauswahl erscheint jetzt auch für `flow` (vorher immer `json`, ohne dass die Seite das zeigte); neue Option `report` (kein Format zu wählen, immer `.docx`).
* `pyproject.toml`: neues Extra `report = ["python-docx"]`. CI installiert neu auch `stats` und `report` (`.github/workflows/ci.yml`), damit die PRISMA-Bild- und DOCX-Tests dort wirklich laufen statt übersprungen zu werden.
* Zurückgestellt (bewusst nicht Teil dieser Runde): Das PRISMA-Bild in den DOCX-Bericht einbetten (würde `matplotlib` **und** `python-docx` gleichzeitig voraussetzen); weitere Export-Formate über die drei angefragten hinaus.
