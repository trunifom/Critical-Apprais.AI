# ADR 0025: Uneinigkeit zwischen Läufen klären - Schiedsrichter und Diskussion

Status: Angenommen als Umsetzungsentscheid des Agenten (2026-10-02); baut auf ADR 0024 (Vergleich mehrerer Läufe) auf

## Ausgangslage
Die Projektleitung wünschte, aufbauend auf dem Lauf-Vergleich (ADR 0024), zwei zusätzliche Wege, Uneinigkeit zwischen Läufen
automatisch zu klären:

1. Ein zusätzliches "Master"-Modell liest beide Begründungen und entscheidet.
2. Die ursprünglichen Modelle "diskutieren" (sehen die Gegenmeinung, dürfen ihre Entscheidung überdenken) über mehrere Runden;
   ohne Konsens entscheidet die Mehrheit oder der Datensatz wird als `NO_CONSENSUS` markiert.

Per Rückfrage (`AskUserQuestion`, 2026-10-02) entschieden: Fallback ohne Konsens = Mehrheit, sonst `NO_CONSENSUS` (echtes Patt
zählt immer als kein Konsens, auch wenn `tie_break: majority` eingestellt ist); Standard 3 Diskussionsrunden, einstellbar;
Schiedsrichter nutzt die **aktuellen** `llm:`-Einstellungen, die Diskussionsteilnehmer nutzen **je ihr eigenes**, ursprüngliches
Modell (aus dem Manifest des jeweiligen Laufs), nicht die aktuelle Konfiguration - sonst wäre es kein Gespräch zwischen
verschiedenen Modellen.

## Entscheidung
1. **Eine Klärung (Schiedsrichter oder Diskussion) wird gespeichert wie ein gewöhnlicher Screening-Lauf**
   (`runs/<lauf-id>/manifest.json`, `screening.jsonl`, `control.json`), nicht als eigener Dateityp. Einziger Unterschied:
   `manifest.kind` ist `adjudicate` oder `discuss` statt `full`/`sample`, und ein paar sonst ungenutzte `ResultRow`-Felder
   (`source_decisions`, `consensus`, `rounds_used`, `tie_break`, `history`) werden gefüllt. Dadurch funktionieren Sperre,
   `crapai runs`, `crapai pause`/`stop` und `--resume` unverändert mit; `resolvable_runs` (neu) und
   `services.results.runs_with_results` (angepasst) halten eine Klärung aus der gewöhnlichen Auswertung und dem Lauf-Vergleich
   heraus, weil sie nur die umstrittenen Datensätze enthält, nicht alle. Keine Schema-Version-Änderung nötig (die neuen Felder
   sind optional mit Standardwert).
2. **Schiedsrichter (`crapai adjudicate`):** ein Aufruf je umstrittenem Datensatz mit der aktuellen `llm:`-Konfiguration; der
   Prompt zeigt Datensatz, Kriterien und jede Meinung (Lauf/Modell, Entscheid, Begründung) in `<opinion>`-Blöcken. Gleiches
   Antwortschema wie beim Screening (`screening/answer.py`), also gleiche Garantie: eine unlesbare Antwort wird nie zu einem
   Entscheid, sondern zu einem Fehlerstatus (`parse_error` usw.).
3. **Diskussion (`crapai discuss`):** Jeder ursprüngliche Lauf wird mit **seinem eigenen** Anbieter/Modell erneut aufgerufen
   (`participant_config` liest `base_url`/`api_key_env`/Modell/Temperatur usw. aus **diesem Laufs** `manifest.json`, nicht aus
   `project.yaml`). Dafür wurde `_new_manifest` in `services/screening.py` um `base_url` und `api_key_env` ergänzt (keine
   Geheimnisse: nur der Variablenname, wie in `project.yaml` selbst). Runde 0 = die ursprünglichen Entscheide (kein neuer
   Aufruf); Runde 1 bis `discussion.max_rounds`: jeder Teilnehmer sieht die aktuelle Gegenmeinung alle anderen und darf seine
   Entscheidung ändern. Stimmen nach einer Runde alle überein, ist das der Konsens. Sonst, nach der letzten Runde:
   `discussion.tie_break` (`majority`, Standard, oder `no_consensus`) entscheidet; ein echtes Patt ergibt immer
   `NO_CONSENSUS`, unabhängig von der Einstellung.
4. **Ein Problem mit einem einzelnen Anbieteraufruf** (defekte Antwort, Sicherheitsfilter, Kontext zu lang) wird zu einem
   Fehlerstatus für genau diesen Datensatz (Schiedsrichter) bzw. dazu, dass dieser Teilnehmer seine vorherige Meinung behält
   (Diskussion) - nie zu einer stillen Vermutung. Ein **Schlüsselproblem** (`AuthError`) oder **aufgebrauchtes Guthaben**
   (`QuotaExceeded`) beendet dagegen den **ganzen** Klärungslauf (Zustand `failed` bzw. `paused`, fortsetzbar), genau wie beim
   normalen Screening (`RunAbort`-Prinzip, hier `_Abort`).
5. **Rückfallebene statt Reihe:** Pause/Stopp während einer Klärung ist grobkörniger als beim Screening (Prüfung von
   `control.json` nur zwischen Päckchen von `limits.max_concurrency * 2` Datensätzen, keine feine Unterbrechung mitten im
   Päckchen) - eine bewusste Vereinfachung, weil eine Klärung nur die (meist kleine) Menge der umstrittenen Datensätze
   umfasst, nicht das ganze Projekt.

## Folgen
* Neue Module `prompts/resolution.py` (Prompt-Bausteine, reines), `services/resolution.py` (Ablauf: `disputed_items`,
  `adjudicate_project`, `discuss_project`, `participant_config`, `resolvable_runs`).
* Neue Einstellungen `discussion.max_rounds` (Standard 3) und `discussion.tie_break` (Standard `majority`) in `project.yaml`.
* `services/screening.py`: `make_provider` in `build_provider` (wiederverwendbar mit beliebigen Feldern) aufgeteilt;
  `_new_manifest` speichert neu `base_url`/`api_key_env` (Grundlage für Punkt 3).
* Neue Befehle `crapai adjudicate --runs <id1,id2,...>` und `crapai discuss --runs <id1,id2,...> [--max-rounds N]
  [--tie-break majority|no_consensus]`, beide mit `--resume`, `--yes`, `--json`, Kostenwarnung vor dem Start (Anzahl
  umstrittener Datensätze, keine Tokenschätzung wie bei `crapai screen` - das wäre für diesen kleineren, variableren Umfang
  unverhältnismässig).
* Zurückgestellt (bewusst nicht gebaut): ein Vergleich gegen menschliche Entscheidungen (Plan Kap. 14, "Gegen Mensch");
  Oberflächen-Schaltflächen, um `adjudicate`/`discuss` direkt zu starten (vorerst nur Befehlszeile, wie `compare-runs` zu
  Beginn).
