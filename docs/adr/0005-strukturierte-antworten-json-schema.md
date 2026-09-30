# ADR 0005: Strukturierte Antworten (JSON-Schema)

Status: Angenommen (Planungsstand 2026-09-30)

## Entscheidung
Das Modell antwortet mit Verdikt je Kriterium und Entscheidung (Kap. 10.3). Legacy-Format `XXX/YYY` bleibt als Vergleichsmodus.

## Alternativen
Freitext mit Sonderzeile (L4, L7, L14)

## Folgen
Ungültige Antworten werden zu `parse_error`, nie zu einem Label. Anbieter ohne Schema-Ausgabe (SwissGPT laut Spezifikation) brauchen Validierung im Code.
