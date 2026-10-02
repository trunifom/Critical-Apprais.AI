# ADR 0015: Volltext-Screening nicht in Version 1

Status: **Ersetzt durch ADR 0026** (Entscheid der Projektleitung, 2026-10-02). Dieser Eintrag bleibt als Verlauf stehen, siehe `docs/adr/0026-volltext-screening.md` für die aktuelle Lage.

Ursprünglicher Status: Angenommen (Entscheid der Projektleitung, 2026-09-30)

## Entscheidung
Version 1 macht **Titel-/Abstract-Screening**. Volltext-Screening wird später ergänzt (Plan Kap. 8.9, 25.6, 29.8, Meilenstein M7).

## Rahmen für später
Es werden nur **Open-Access-PDFs** verarbeitet; die Hochschule verfügt zudem über lizenzierte Zeitschriften. Lizenzfragen gelten damit als unkritisch (Angabe der Projektleitung). Die Datenweitergabe an den Anbieter wird trotzdem im Projekt bestätigt (`acknowledgements.data_transfer`).

## Folgen
- Aufgabe T-M1-09 (PDF-ZIP-Reader) ist zurückgestellt; Fixtures (`test.zip`) bleiben für später.
- `mode: fulltext` in `project.yaml` wird in v1 abgelehnt mit klarer Meldung.
- Die Daten-Modelle (`fulltext_of`, `fulltext_path`) bleiben im Schema reserviert.
