# ADR 0029: KI-Vorfilter mit Jev (TypeSafe AI) als expliziter Spezialmodus

Status: Angenommen (Entscheid der Projektleitung im Chat, 2026-10-02)

## Ausgangslage

Im Chat wurde recherchiert, ob "Jev" (TypeSafe AIs "System-One"-Entscheidungsmodell, Launch
15.09.2026) sich für die Screening-Entscheidungen dieses Projekts eignet. Jev ist kein
Chat-Completion-Modell: ein Aufruf stellt eine oder mehrere typisierte Fragen (`choice`/`score`/
`noul`) über einen Text und erhält eine typisierte Antwort mit kalibrierten Wahrscheinlichkeiten
zurück - nie Fliesstext. Veröffentlichte Benchmarks zeigen eine Genauigkeit von rund 68 % (einige
Punkte unter Spitzen-Sprachmodellen), aber gute Kalibrierung ab Konfidenz ~0.9 aufwärts; dafür ist
Jev deutlich schneller und günstiger (Veröffentlichte Preise: 0.042 USD je Million Eingabe-Tokens,
Ausgabe gratis).

Der entscheidende Unterschied zu diesem Projekt: jede Screening-Entscheidung (`ResultRow`,
`screening/store.py`) verlangt pro Kriterium ein Zitat und eine Begründung (Nachvollziehbarkeit für
ein systematisches Review, PRISMA). Jev kann das grundsätzlich nicht liefern - es gibt nur die
nackte Entscheidung plus Wahrscheinlichkeit zurück. Jev ersetzt daher **nicht** den eigentlichen
Screening-Schritt. Es eignet sich aber als schneller, sehr günstiger **Vorfilter**, der bei hoher
Konfidenz klar themenfremde Datensätze markiert, bevor der normale (begründungsfähige) LLM-Lauf
beginnt.

Auftrag der Projektleitung: genau das implementieren, aber nur als klar erklärter **Spezialmodus**,
den man explizit einschalten und separat starten muss - niemals automatisch Teil von `crapai
check`/`crapai screen`.

## Entscheidung

1. **Zwei getrennte Tore, beide nötig.** Tor 1: `ai_prefilter.enabled` in `project.yaml` muss aktiv
   eingeschaltet werden (Standard: aus); ohne das verweigert der Dienst selbst mit einer klaren
   `ConfigError` (E203), auch wenn der Befehl direkt aufgerufen wird. Tor 2: ein eigener,
   dedizierter Befehl `crapai jev-prefilter FOLDER [--yes]` (eigene Kostenvoranschlag-→-Bestätigen-
   Abfolge wie `crapai screen`) bzw. eine eigene GUI-Seite mit Bestätigungs-Checkbox. Der Vorfilter
   ist **nie** Teil von `crapai check`/`crapai screen` und läuft nie automatisch mit.
2. **Eigener, isolierter Ausschlussgrund** `AI_PREFILTER_JEV` (`prisma/reasons.py`), bewusst
   **ausserhalb** von `PREFILTER_REASONS`/`VALIDITY_REASONS`/`REPLACEABLE_BY_DEDUP`: Die
   automatische Kette (`crapai check`/`crapai screen` ruft immer `apply_dedup()` →
   `apply_prefilters()` → `apply_validity()` auf) darf diese Markierung nie stillschweigend löschen
   oder überschreiben - sie wurde ja nicht von dieser Kette gesetzt und kann von ihr auch nicht neu
   berechnet werden. `mark_prefilters()`/`mark_validity()` rühren nur ihre eigenen Grund-Mengen an;
   Dedup ersetzt nur Gründe aus `REPLACEABLE_BY_DEDUP`. Ein Datensatz, den Jev schon ausgeschlossen
   hat, bleibt deshalb exakt so markiert, über beliebig viele weitere `crapai check`-Läufe hinweg.
3. **Eine einzige Frage, nur das `noul`-Primitiv.** Pro Datensatz genau eine `noul`-Frage: "Ist aus
   Titel/Abstract allein klar, dass dieser Datensatz die Einschlusskriterien NICHT erfüllt?" Die
   Kriterien kommen unverändert aus `prompts.builder.criteria_block()` (keine neue Kriterien-
   Logik). `choice`/`score` werden nicht verwendet (nicht gebraucht für diese eine Entscheidung).
4. **Nur Vor-Ausschluss, nie Vor-Einschluss, nur bei hoher Konfidenz.** Antwort `true` (erfüllt die
   Kriterien nicht) **und** Konfidenz ≥ `ai_prefilter.confidence_floor` (Standard 0.9, harte
   Untergrenze 0.85 - die veröffentlichte Kalibrierung ist erst ab ca. 0.9 verlässlich) markiert den
   Datensatz. Jeder andere Fall (Antwort `false`, oder `true` mit zu geringer Konfidenz, oder ein
   Fehler) lässt den Datensatz **unverändert** - er geht normal ins gewöhnliche Screening. Die volle
   Rohantwort (Wahrscheinlichkeiten, Konfidenz, Kosten, Tokens) wird in `extra_json["jev"]`
   gespeichert, die kurze Zusammenfassung in `exclusion_details` - beides bestehende, freie Felder
   von `Record`, keine Schema-Version-Erhöhung nötig.
5. **Eigener Client, kein `LLMProvider`.** `llm/jev_client.py` (`JevClient`, `MockJevClient`) ist
   bewusst **kein** `LLMProvider`: dessen `complete()` liefert Text zum Parsen durch
   `screening.answer`, Jevs Antwort ist aber bereits typisiert und hat keinen Text. Fehler werden in
   dieselben Klassen übersetzt wie beim OpenAI-Anbieter (`AuthError`/`RateLimited`/
   `TransientError`/`ContextTooLong`/`QuotaExceeded`) und mit denselben Werkzeugen wiederholt
   (`llm/resilience.py`, unverändert wiederverwendet). Neues, separates Extra `prefilter-jev =
   ["httpx"]` (`pyproject.toml`), verzögerter Import wie beim `openai`-Paket.
6. **PRISMA-Zahlen bleiben korrekt und nachvollziehbar.** Ein neues `EventType.INFO`-Ereignis mit
   `kind="ai_prefilter_jev"` (analog zu `kind="prefilter"`), ein neuer, eigener Fold-Zweig in
   `prisma/flow.py::build_flow()` mit eigenen `PrismaFlow`-Feldern
   (`records_removed_by_ai_prefilter`, `ai_prefilter_reasons`), beide in
   `records_removed_before_screening_other`/`records_to_screen` eingerechnet. Anders als beim
   deterministischen Vorfilter gibt es **keine** "stale, wenn Dedup danach lief"-Behandlung: Dedup
   ersetzt `AI_PREFILTER_JEV` nie (Punkt 2), also kann ein späterer Dedup-Lauf diese Momentaufnahme
   nie ungültig machen.
7. **Immer erklärt, auch wenn ausgeschaltet.** Die GUI-Seite (`ui/pages/jev.py`, eigener Menüpunkt,
   bewusst **nicht** Teil von `build_stepper()`s Pflichtschritten) zeigt die Erklärung (was Jev ist,
   die recherchierten Genauigkeits-/Kalibrierungszahlen, was es nicht tut) auch bei ausgeschaltetem
   Vorfilter, bevor irgendjemand ihn einschaltet.

## Folgen

* Neue Datei `src/crapai/llm/jev_client.py` (`JevClient`, `MockJevClient`, `JevDecision`,
  `translate`).
* Neue Datei `src/crapai/services/ai_prefilter.py` (`ai_prefilter_project`, `apply_ai_prefilter`,
  `build_client`, `eligible_for_ai_prefilter`, `AiPrefilterSummary`).
* `src/crapai/config/models.py`: neues `AiPrefilterOptions`, neues Feld `ai_prefilter` in
  `ProjectConfig` (Geschwisterfeld von `prefilters`, nicht darin verschachtelt).
* `src/crapai/prisma/reasons.py`: neue Konstante `AI_PREFILTER_JEV`, eigenes `frozenset`
  `AI_PREFILTER_REASONS`. `src/crapai/io/records_store.py`: `EXCLUSION_REASONS` erweitert.
* `src/crapai/prisma/events.py`/`flow.py`, `src/crapai/services/events.py`: neues Ereignis und
  Fold-Zweig (siehe Entscheidung 6).
* `src/crapai/services/cost.py`: neue `estimate_ai_prefilter()`/`AiPrefilterEstimate` (nutzt
  `CharTokenizer` und die bestehende `pricing.csv`-Logik, keine neue Preis-Architektur).
* `src/crapai/cli.py`: neuer Befehl `crapai jev-prefilter`.
* Oberfläche: neue Seite `jev` (`ui/pages/jev.py`), neuer Abschnitt in den Einstellungen
  (`settings_form.py`), neue Aktionen in `ui/actions.py` (`estimate_jev`, `run_jev_prefilter`,
  synchron mit Spinner, kein Hintergrundprozess).
* `pyproject.toml`: neues Extra `prefilter-jev = ["httpx"]`. `templates/pricing.example.csv`: neue
  Beispielzeile `typesafe,jev-latest,...`.
* Zurückgestellt (bewusst nicht Teil dieser Runde): kein Hintergrundprozess/Pause/Resume für den
  Vorfilter-Lauf selbst (er ist laut Spezifikation schnell/günstig; bei Abbruch wird nichts
  geschrieben, ein Schreibvorgang am Ende wie beim deterministischen Vorfilter); keine eigene Box
  im PRISMA-Flussdiagramm-**Bild** (nur in den JSON-Zahlen/im Bericht); kein Vergleich gegen
  menschliche Entscheidungen dieses Projekts; `choice`/`score`-Primitive von Jev ungenutzt.
