# ADR 0009: pyproject.toml mit Extras und Lockfile

Status: Angenommen (Planungsstand 2026-09-30)

## Entscheidung
Basis-Abhängigkeiten klein (pandas, pydantic, pyyaml); Import/LLM/CLI/UI als Extras.

## Alternativen
Conda-Export (`requirements.txt` des Bestands ist plattformspezifisch, L13)

## Folgen
Reproduzierbare Installation; Lockfile (uv) in Aufgabe T-M0-02.
