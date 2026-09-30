# ADR 0001: Projektordner statt Datenbank

Status: Angenommen (Planungsstand 2026-09-30)

## Entscheidung
Alle Zustände liegen als Dateien im Projektordner (Plan Kap. 6). Keine SQL-Datenbank, auch kein SQLite.

## Alternativen
SQLite (einfacher abzufragen, aber nicht menschenlesbar, widerspricht der Anforderung)

## Folgen
Dateiformate sind Vertrag (Kap. 25/26). Sperren und atomares Schreiben müssen selbst gelöst werden (Kap. 28.9).
