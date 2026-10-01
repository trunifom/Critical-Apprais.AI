# ADR 0024: Mehrfachbewertung als unabhängige Läufe plus eigene Vergleichsschicht

Status: Angenommen als Umsetzungsentscheid des Agenten (2026-10-01); setzt Plan Kap. 14.1 um

## Ausgangslage
Auf Wunsch der Projektleitung soll dasselbe Projekt mehrfach bewertet werden können - mit demselben Modell (Test-Retest) oder mit
verschiedenen Modellen (Modellvergleich, Beispiel der Projektleitung: SwissGPT Neotron, ChatGPT GPT-4o, ChatGPT GPT-4o ein zweites
Mal) - und am Ende die Antworten nebeneinander im Ausgabefile sehen, inklusive Übereinstimmung. Zwei Umsetzungsfragen waren offen und
wurden der Projektleitung vorgelegt (`AskUserQuestion`, 2026-10-01):

1. Soll das in einem Lauf passieren (jedes Papier mehrfach hintereinander) oder durch mehrfaches Hochladen/Anhängen? -> der
   Projektleitung überlassen.
2. Wie wird die Mehrfachbewertung angestossen? Entschieden: **mehrere separate `crapai screen`-Aufrufe** (nicht ein Befehl mit
   Modell-Liste, der automatisch mehrere Läufe nacheinander startet).

## Entscheidung
1. **Keine Änderung an der Screening-Engine.** Ein Lauf bleibt "ein Provider, ein Modell, ein Prompt" (`ScreeningEngine` nimmt genau
   einen `LLMProvider` und einen `PromptBuilder`). Mehrfachbewertung heisst: `project.yaml` zwischen den Aufrufen anpassen
   (`llm.provider`/`llm.model`, per Hand, Oberfläche oder `crapai config set`) und `crapai screen` erneut ausführen. Jeder Aufruf
   erzeugt einen eigenen, unabhängigen Ordner `runs/<lauf-id>/` mit eigenem Manifest - genau das Verhalten, das der Plan für
   `--repeats N` ohnehin vorsieht (Kap. 14, Zeile 531: "Jeder Lauf hat sein eigenes Manifest. Die Läufe teilen sich nichts ausser den
   Eingabedaten."). Diese Architektur existierte bereits (`runs_with_results`, `list_runs`); es musste nichts dafür geändert werden.
2. **Neue, reine Vergleichsschicht** `stats/agreement.py`: paarweise Übereinstimmung und Cohens Kappa je Lauf-Paar (auf der
   Schnittmenge der von **beiden** Läufen entschiedenen Datensätze), Fleiss' Kappa über alle gewählten Läufe zusammen (auf der
   Schnittmenge aller), Einstufung nach Landis & Koch (1977), Liste der uneinigen Datensätze. Nur Entscheidungen mit Status `ok` und
   bekanntem Wert (`INCLUDE`/`EXCLUDE`/`UNCERTAIN`) zählen; ein von einem Lauf noch nicht erreichter oder fehlerhaft beantworteter
   Datensatz ist keine Uneinigkeit, sondern (noch) nicht vergleichbar.
3. **Neue Vergleichstabelle** `stats.results.compare_table`/`compare_columns`: eine Zeile je Datensatz des Projekts, Basisspalten
   (`study_uid`, `title`, `year`, `journal`, `exclusion_reason`) plus vier Spalten je gewähltem Lauf (`status__<lauf-id>`,
   `decision__<lauf-id>`, `reasoning__<lauf-id>`, `model_returned__<lauf-id>`) und eine `agreement`-Spalte (leer/`partial`/
   `unanimous`/`split`) - das "angehängte" Ausgabefile, das die Projektleitung wünschte, ohne die bestehende Einzel-Lauf-Tabelle
   (`build_table`, `RESULT_COLUMNS`) anzutasten.
4. **Dienst** `services.results.compare_runs`/`export_comparison`: liest die Läufe (mindestens zwei, sonst E203), baut Tabelle und
   Übereinstimmung, exportiert nach `exports/compare-<läufe>-<zeitstempel>.csv`/`.xlsx`. Liest nur, ändert nichts, braucht keine Sperre.
5. **Befehl** `crapai compare-runs <projekt> --runs <id1,id2,...>`: schreibt die Datei und gibt die Übereinstimmungszahlen auf der
   Konsole aus (Rückgabecode 4 nur bei gesperrter Zieldatei, sonst 0/1/2 wie gewohnt).
6. **Oberfläche** (Seite „Auswertung“, Abschnitt „Läufe vergleichen“, nur sichtbar ab zwei abgeschlossenen Läufen): Mehrfachauswahl
   der Läufe, Tabelle der paarweisen Kennzahlen, Fleiss' Kappa als Kennzahl, gruppiertes Balkendiagramm der Entscheidungen **je Lauf
   in eigener Farbe** (`ui.charts.run_bars`/`run_scale`, neue, von den Ergebniskategorien unabhängige Farbskala), Liste der uneinigen
   Datensätze.

## Folgen
* Neue Module `stats/agreement.py`; neue Funktionen in `stats/results.py` (`compare_table`, `compare_columns`) und
  `services/results.py` (`compare_runs`, `export_comparison`); neuer CLI-Befehl `compare-runs`; neue UI-Funktionen
  `ui.actions.compare_runs`, `ui.charts.run_bars`/`run_scale`, Abschnitt in `ui/pages/results.py`.
* Kein Schema-Sprung, keine Änderung an `runs/<lauf-id>/manifest.json` oder `screening.jsonl`: die Vergleichsschicht liest nur,
  was bereits da ist.
* Zurückgestellt (nicht gebaut): ein Komfortbefehl, der mehrere Modelle automatisch nacheinander durchläuft (`--repeats N` aus dem
  Plan), und Vergleich gegen menschliche Entscheidungen (Plan Kap. 14, "Gegen Mensch") - beides ausserhalb des hier gestellten
  Wunsches.
