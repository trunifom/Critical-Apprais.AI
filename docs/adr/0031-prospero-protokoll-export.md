# ADR 0031: PROSPERO-Protokoll-Export (vorausgefülltes Dokument, keine Einreichung)

Status: Angenommen (Entscheid der Projektleitung im Chat, 2026-10-02)

## Ausgangslage

Auf die Frage, was für eine Literaturrecherche-Software noch wichtig wäre, wurde u. a. eine
PROSPERO-Anbindung genannt. Recherche vorab: **PROSPERO** (das internationale Register für
Review-Protokolle, geführt vom Centre for Reviews and Dissemination der University of York) hat
**keine öffentliche Einreichungs-API** - nur ein Webformular, das ein benannter Garant ("named
guarantor") bestätigen muss, bevor die Registrierungsnummer vergeben wird. Eine automatische
Einreichung ist damit technisch nicht möglich, unabhängig vom Aufwand.

Was stattdessen machbar und nützlich ist: ein **Dokument**, das so viele Felder des
PROSPERO-Formulars wie möglich aus bereits in diesem Projekt vorhandenen Daten (Titel, Ziele,
Ein-/Ausschlusskriterien, Sprach-/Jahreseinschränkungen) vorausfüllt, damit die Übertragung ins
Webformular schneller geht - mit einem sichtbaren Platzhalter überall dort, wo PROSPERO mehr wissen
will, als dieses Projekt erfasst (Suchstrategie/Datenbankliste, Risk-of-Bias-Methode,
Synthese-Plan, Team, Finanzierung, Interessenkonflikte, Daten).

## Entscheidung

1. **Kein Einreichungs-Feature, nur ein Entwurfs-Dokument.** `crapai export mein-review --what
   prospero` schreibt ein `.docx` (`exports/prospero-<Zeitstempel>.docx`), das der Mensch selbst
   ins PROSPERO-Webformular überträgt. Das Dokument sagt das selbst ausdrücklich am Anfang ("it is
   not submitted automatically; PROSPERO has no public submission API").
2. **Wiederverwendung des bestehenden Musters**, keine neue Infrastruktur:
   `io/writers/prospero_protocol.py` folgt `io/writers/docx_report.py` 1:1 (verzögerter
   `python-docx`-Import, `ConfigError` E203 mit Installationshinweis, gleiche
   `document.add_heading`/`add_paragraph`/`add_table`-Bausteine). **Keine neue Abhängigkeit**: das
   Extra `report` (`python-docx`) existiert bereits.
3. **Neues, eigenständiges Konfigurationsmodell `Prospero`** (`config/models.py`) für die acht
   Felder, die PROSPERO abfragt und sonst nirgends in diesem Projekt vorkommen (Start-/
   Abschlussdatum, Stand, Team, korrespondierende Autorin/Autor, Finanzierung,
   Interessenkonflikte, frühere Registrierung). Alle Felder sind freiwillig/leer per Vorgabe und
   steuern **kein** anderes Verhalten - sie dienen ausschliesslich diesem einen Export.
4. **Fehlende Angaben werden sichtbar, nie verschwiegen.** Jeder Abschnitt wird immer geschrieben;
   eine leere Angabe erscheint als Platzhaltertext ("(please complete -- not tracked by this
   project)"), nie als weggelassene Überschrift - gleiches Prinzip wie beim bestehenden
   Zusammenfassungsbericht für ein Projekt ohne abgeschlossenen Lauf.
5. **Die "Searches"-Rubrik wird ausdrücklich als unvollständig benannt.** Dieses Projekt erfasst
   nur eine Sprach- und eine Jahreseinschränkung (`prefilters.language`/`.year`), keine echte
   Suchstrategie oder Datenbankliste. Das Dokument sagt das wörtlich, statt die schwachen
   Platzhalter (`prefilters.keywords`/`.publication_types`) so zu präsentieren, als wären sie eine
   vollständige Suchstrategie.
6. **Kein neuer Menüpunkt in der Oberfläche.** Die bestehende Export-Seite bekommt eine vierte
   Auswahl ("PROSPERO-Protokoll-Entwurf (DOCX)") neben Datensätze/Ergebnisse/Fluss/Bericht, genau
   wie der bestehende Zusammenfassungsbericht behandelt (kein Format zu wählen, immer `.docx`).

## Folgen

* Neue Datei `src/crapai/io/writers/prospero_protocol.py`
  (`build_prospero_protocol`, `write_prospero_protocol`).
* `src/crapai/config/models.py`: neues Modell `Prospero`, neues Feld `prospero` in `ProjectConfig`.
* `src/crapai/services/export.py`: neue Funktion `export_prospero()`.
* `src/crapai/cli.py`: `crapai export --what prospero` (ergänzt `records|results|flow|report`).
* Oberfläche: Export-Seite (vierte Auswahl), Einstellungen-Seite (neuer Abschnitt `prospero`).
* Zurückgestellt (bewusst nicht Teil dieser Runde): jede Form der automatischen Einreichung (es
  gibt keine API dafür); ein Abgleich mit bereits bei PROSPERO registrierten Protokollen; eine
  Validierung gegen PROSPERO-spezifische Pflichtfelder-Regeln - das Dokument ist eine Abschrift zum
  Prüfen und Ergänzen, keine Garantie für Vollständigkeit, und sagt das auch so.
