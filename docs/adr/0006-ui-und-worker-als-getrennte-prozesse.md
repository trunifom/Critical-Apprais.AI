# ADR 0006: UI und Worker als getrennte Prozesse

Status: Angenommen (Planungsstand 2026-09-30)

## Entscheidung
Lange Läufe laufen im eigenen Prozess; Kommunikation nur über Dateien (Manifest, `control.json`, Lock mit Herzschlag) (Kap. 28.4).

## Alternativen
Lauf im Streamlit-Prozess (bricht bei Neuladen ab)

## Folgen
UI ist austauschbar; Läufe überleben Browser-Neustarts.
