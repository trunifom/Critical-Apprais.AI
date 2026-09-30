# ADR 0007: Pydantic v2 und YAML für Konfiguration

Status: Angenommen (Planungsstand 2026-09-30)

## Entscheidung
`project.yaml` wird mit Pydantic validiert (Kap. 16).

## Alternativen
Rohes Dict, dataclasses

## Folgen
Präzise Fehlermeldungen; Schema ist testbar.
