# ADR 0008: Neues Repository, Module kopieren statt Fork

Status: Angenommen (Planungsstand 2026-09-30)

## Entscheidung
Übernommener Code steht in `reference/` (unverändert) und wird nach `src/` portiert (`docs/MIGRATION.md`).

## Alternativen
Fork von SARA-App

## Folgen
Historie und Deployment der App bleiben unberührt; Portierung bewusst und getestet.
