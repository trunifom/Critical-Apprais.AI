# ADR 0026: Volltext-Screening mit PDF-Dokumenten (löst ADR 0015 ab)

Status: Angenommen (Entscheid der Projektleitung, 2026-10-02); hebt ADR 0015 ausdrücklich auf

## Ausgangslage

ADR 0015 hatte Volltext-Screening bewusst auf später (Meilenstein M7) vertagt. Die Architektur dafür
war aber bereits weitgehend vorbereitet: Enums (`ScreeningMode.FULLTEXT`, `EventType.SCREEN_FT`,
`PrismaWorkflowState.FULLTEXT_SCREENED`), reservierte Spalten in `records.csv` (`has_fulltext`,
`fulltext_path`, `fulltext_of`, `zip_member`), ein bereits aktives PRISMA-Feld
(`reports_excluded_fulltext`, berechnet aus `EventType.SCREEN_FT`-Ereignissen), zwei fertige
Prompt-Varianten (`baseline_fulltext.yaml`, `gpt_improved_fulltext.yaml`), `pymupdf`/`pdfplumber`
bereits im `import`-Extra, die voll spezifizierte Aufgabenkarte T-M1-09 und die Plankapitel 8.9, 25.6
und 29.8 mit konkreten Algorithmen und Schwellen. Die Projektleitung hat (Chat, 2026-10-02) beauftragt,
dies jetzt umzusetzen.

## Entscheidung

1. **Nur PDF-Zip-Import**, kein Einzel-PDF-Import in v1 dieses Features. `crapai import <projekt>
   pdfs.zip` liest ein Zip mit PDFs (nie extrahiert, nur `zf.read()`/`zf.open()` - Zip-Slip-Schutz),
   überspringt `__MACOSX/`, `._`-Dateien, Verzeichnisse und alles ausser `.pdf`. Jede PDF wird per
   DOI-Regex oder unscharfem Titel-Abgleich einem **bestehenden** Datensatz aus `records.csv`
   zugeordnet (`fulltext_of = study_uid`); das ist eine Ausnahme vom sonst durchgängigen
   Anhänge-Muster beim Import - dieser Importpfad **aktualisiert** bestehende Zeilen statt neue
   anzuhängen, und ist deshalb als eigene, klar benannte Funktion umgesetzt, nicht als Sonderfall in
   der allgemeinen Importfunktion. Nicht zugeordnete PDFs werden nicht verworfen, sondern in
   `reports/unmatched_pdfs.csv` aufgeführt (Grundsatz: nichts geht still verloren).
2. **Nur Datensätze mit Titel-/Abstract-Einschluss (INCLUDE/UNCERTAIN) und zugeordneter PDF** werden
   zum Volltext-Screening zugelassen. Ein zugeordneter, aber qualitativ unbrauchbarer Volltext
   (`NO_TEXT`, `ENCRYPTED`, `IMPORT_ERROR` - aus dem PDF-Lesevorgang) wird markiert, nie stillschweigend
   übersprungen. Ein Datensatz ohne zugeordnete PDF bekommt beim Volltext-Lauf
   `exclusion_reason_code = no_fulltext`, statt ihn einfach auszulassen.
3. **Drei Strategien** (`screening.fulltext.strategy`, `project.yaml`): `truncate` (auf das
   Kontextfenster kürzen), `sections` (nur Methods/Results/Discussion behalten), `map_reduce`
   (Text in Abschnitte teilen, pro Abschnitt Belege sammeln, am Ende zusammenführen - teuerster, aber
   gründlichster Pfad, 20-40x Abstract-Kosten als Grössenordnung laut Plan Kap. 29.8; dafür ein
   deutlicher Kostenhinweis vor dem Lauf). `screening.fulltext.repeat_criteria_after_text` wiederholt
   die Kriterien nach dem Volltext-Block (Modelle gewichten Kontext kurz vor der Frage stärker).
4. **Kein neuer Dateityp:** Ein Volltext-Lauf ist ein gewöhnlicher Screening-Lauf
   (`project.mode: fulltext` statt `abstract`), gespeichert wie jeder andere unter `runs/<id>/`.
   Nach Abschluss wird ein `EventType.SCREEN_FT`-Ereignis geschrieben (analog zum bestehenden
   `SCREEN_TA` nach Abstract-Läufen); `prisma/flow.py::build_flow()` verarbeitet das bereits
   vollständig, keine Änderung an der PRISMA-Berechnung nötig.
5. **Rahmen bleibt wie in ADR 0015 beschrieben:** nur Open-Access-PDFs werden verarbeitet;
   `acknowledgements.data_transfer` bleibt Pflichtbestätigung vor jedem Lauf, der Daten an einen
   Anbieter schickt - auch im Volltext-Modus.

## Folgen

* Neue Datei `src/crapai/io/readers/pdf_zip.py` (T-M1-09, jetzt umgesetzt statt zurückgestellt).
* `src/crapai/io/readers/dispatch.py`: ZIP-Format wird an `read_pdf_zip()` weitergereicht statt
  pauschal abgelehnt.
* `src/crapai/config/models.py`: `ProjectInfo.mode` erweitert auf
  `Literal["abstract", "fulltext"]`; der Validator `_fulltext_is_not_in_v1` entfällt.
* Neue reine Hilfsmodule `src/crapai/prompts/fulltext_sections.py` (Abschnitts-Erkennung) und
  `src/crapai/screening/fulltext.py` (`prepare_fulltext()`: die drei Strategien als testbare
  Funktionen, getrennt von der Engine, damit `engine.py` nicht zu einem Monolithen wird).
* `src/crapai/prompts/builder.py`: neue Methode `build_fulltext()`; die bereits vorhandenen
  `baseline_fulltext.yaml`/`gpt_improved_fulltext.yaml`-Varianten werden damit erstmals nutzbar.
* `src/crapai/screening/engine.py`, `src/crapai/screening/store.py`: `PlanItem.fulltext`,
  `ResultRow.exclusion_reason_code` (neues, additives Feld, Schema-Version erhöht).
* `src/crapai/services/cost.py`: Kostenschätzung berücksichtigt Volltext-Länge und -Strategie
  (bei `map_reduce` mit Chunk-Anzahl multipliziert, sonst wäre die Schätzung systematisch zu niedrig).
* Oberfläche: Zip-Upload auf der Daten-Seite, Modus-Auswahl auf der Einstellungen-Seite (nur
  wechselbar, wenn mindestens eine PDF zugeordnet ist), Kostenwarnung bei `map_reduce` auf der
  Lauf-Seite.
* Zurückgestellt (bewusst nicht Teil dieser Runde): Einzel-PDF-Import ohne Zip; OCR für gescannte
  PDFs (`ocrmypdf`/`pytesseract`, Plan Kap. 8.9 nennt das als späteren Opt-in); Vergleich gegen
  menschliche Volltext-Entscheidungen (Plan Kap. 14).
