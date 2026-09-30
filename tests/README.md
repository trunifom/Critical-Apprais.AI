# tests/

Ausführen (Projektwurzel): `python -m pytest -q` (ca. 25 s). Schnell ohne Legacy-Läufe: `python -m pytest -q tests/unit -k "not golden"`.

## Inhalt

| Ordner | Inhalt | Verwendung |
|---|---|---|
| `unit/` | Tests aller Module (Anzahl: `docs/UMSETZUNGSPLAN_UND_FORTSCHRITT.md`) | Vorlage für neue Tests |
| `integration/` | Meilenstein A: alle Fixtures über die echte CLI importieren; ab T-M3-07 auch Ende-zu-Ende mit `MockProvider` | |
| `data/` | Kleine Fixtures aus öffentlichen Datenbank-Exporten + `EXPECTED.json` | Reader-, Dedup-, Preflight-Tests |
| `data_large/` | Grosse Fixtures (nicht versioniert, siehe dortige README) | Leistungs-/PDF-Tests, Marker `large` |
| `legacy_runs/` | 16 Ergebnis-CSV aus 3 SARA-App-Projekten (`;`-getrennt, gemischte Kodierung) | Golden-Test Test-Retest, Legacy-Import |
| `expected/` | Berichte (`.txt`/`.csv`) der alten Statistik-Skripte | Sollwerte |

## Fixtures in `tests/data/` (Datensatzzahlen aus `EXPECTED.json`, unabhängig geprüft)

| Datei | Format | Datensätze | Besonderheit |
|---|---|---|---|
| `example_db_nr1_total-15_duplicates-0.ris` | RIS | **13** (Name sagt 15!) | keine Abstracts, keine Duplikate |
| `example_db_nr2_total-10_duplicates-3.ris` | RIS | 10 (7 eindeutige DOI) | 3 Duplikate |
| `example_db_nr3_total-8_duplicates-2.ris` | RIS | 8 (6 eindeutige DOI) | 2 Duplikate |
| (nr1+nr2+nr3 zusammen) | | 31 | 13 eindeutige DOI, **18** Duplikate über die Quellen |
| `example_AB_nr4.ris` / `.txt` | RIS | 3 | Endung `.txt`, Abstracts vorhanden |
| `IEEE-Xplore_SR_2023-2024.ris` | RIS | 46 (alle mit Abstract) | CRLF, `T2`=Konferenz, viele `KW`, `EP`/`VO` |
| `citation-export.ris` | RIS (Cochrane) | 6 | `Record #k of n`-Kopfzeilen, `TY  -  JOUR` |
| `citation-export.bib` | BibTeX (Cochrane) | 48 | Zeilen ausserhalb von Einträgen, Feldnamen mit Leerzeichen, Abstracts ohne Leerzeichen an Umbrüchen |
| `citation-export_1.bib` | BibTeX | 9 | |
| `pubmed-adhd-set.nbib` | NBIB/MEDLINE | 100 | |
| `pubmed-adhd-set.ris` | (NBIB als `.ris`) | 100 | byte-identisch zur `.nbib` |
| `pubmed-adhdANDchi-set.nbib` | NBIB | 62 | |
| `pubmed_adhd_converted-zotero.ris` | RIS (Zotero) | 706 (156 `AB`) | 129 Fortsetzungszeilen, `DA`, `L1`, `TY CHAP` ohne Abstract |
| `pubmed_adhd_converted-zotero.bib` | BibTeX (Zotero) | 706 | article 576, book 90, misc 29, incollection 9, inproceedings 2 |

## Regeln

- Fixtures sind schreibgeschützt zu behandeln. Neue Fixtures klein halten (5-20 Datensätze) und in `scripts/build_expected.py`
  aufnehmen.
- Keine personenbezogenen Daten von Teilnehmenden und keine Schlüssel in Testdaten. Die Fixtures sind öffentliche
  Literatur-Exporte; die PubMed-Dateien enthalten im Feld `AD` öffentliche Korrespondenz-E-Mail-Adressen der Autor:innen
  (vor einer Veröffentlichung des Repos entscheiden, ob sie gekürzt werden). Die Legacy-Läufe enthalten Titel/Abstracts
  und Modellantworten.
- Live-Tests (`@pytest.mark.live`) nur manuell.
