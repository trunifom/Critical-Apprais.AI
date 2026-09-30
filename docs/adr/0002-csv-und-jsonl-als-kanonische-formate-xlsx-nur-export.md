# ADR 0002: CSV und JSONL als kanonische Formate, XLSX nur Export

Status: Angenommen (Planungsstand 2026-09-30)

## Entscheidung
`records.csv` und `screening.jsonl` sind Quelle der Wahrheit; `results.xlsx` wird daraus erzeugt.

## Alternativen
Parquet (binär, nicht direkt lesbar), XLSX als Quelle (durch Excel sperrbar/veränderbar)

## Folgen
Ausgaben sind jederzeit neu erzeugbar; Excel-Sperre gefährdet keine Daten.
