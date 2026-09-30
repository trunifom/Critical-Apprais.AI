# ADR 0011: Schlüssel nur per Umgebung oder OS-Schlüsselbund

Status: Angenommen (Planungsstand 2026-09-30)

## Entscheidung
Nie in `project.yaml`, Manifest, Log oder Ergebnissen (Kap. 16.2, 19).

## Alternativen
`.env` im Projektordner

## Folgen
Automatischer Scan im Test (AT8).
