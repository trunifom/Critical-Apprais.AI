# ADR 0003: Append-only-Checkpoint

Status: Angenommen (Planungsstand 2026-09-30)

## Entscheidung
Jede LLM-Antwort wird sofort als JSON-Zeile angehängt (ein Schreiber-Task, flush je Zeile).

## Alternativen
Ergebnisdatei nach jedem Datensatz neu schreiben

## Folgen
Wiederaufnahme trivial; letzte Zeile je `study_uid` gilt; halbe Schlusszeile wird abgeschnitten.
