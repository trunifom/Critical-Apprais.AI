# ADR 0014: SwissGPT (AlpineAI) als voraussichtlicher Hauptanbieter

Status: Angenommen als Ausrichtung (Angaben der Projektleitung, 2026-09-30)

## Entscheidung
Künftig wird vorwiegend **SwissGPT** über die OpenAI-kompatible Schnittstelle genutzt (`provider: openai_compatible`, Basis-URL `https://api.prod.alpineai.ch/v1`). Weitere Anbieter (OpenAI, Anthropic, lokal) bleiben austauschbar.

## Begründung (Angaben der Projektleitung)
Daten verschlüsselt, Verarbeitung in der Schweiz, Löschung nach dem API-Aufruf, keine Nutzung zum Training. Diese Zusicherungen stammen aus der Projektleitung und sind **nicht** aus der API-Spezifikation ableitbar; sie sollten vertraglich/schriftlich belegt und im Manifest bzw. Methodenteil zitierbar abgelegt werden.

## Folgen
- Die SwissGPT-Spezifikation kennt **kein `response_format` und kein `seed`** (`docs/swissgpt/`): strukturierte Antworten müssen im Code validiert werden (`parse_error` statt stiller Label, ADR 0005); Determinismus nicht voraussetzen (Test-Retest).
- Modellliste dynamisch über `GET /v1/models`; Authentifizierung gegen die Live-API prüfen (Plan Kap. 39, D10).
- Aufgabe T-M3-02 baut zuerst den OpenAI-kompatiblen Provider (SwissGPT), dann OpenAI.
