# ADR 0023: Keyword-Filter - deterministischer Vorfilter und optionaler Prompt-Kontext

Status: Angenommen als Umsetzungsentscheid des Agenten (2026-10-01); ergänzt ADR 0019

## Ausgangslage
Auf Wunsch der Projektleitung soll nach Stichwörtern ein- und ausgeschlossen werden können, zusätzlich zu Title und Abstract. Das
Feld `keywords` (und `keywords_mesh`) existiert seit Meilenstein A in `records.csv`, wurde aber bisher nirgends benutzt. Entschieden
(Rückfrage an die Projektleitung, 2026-10-01): **beide** Varianten, unabhängig zuschaltbar.

## Entscheidung
1. **Deterministischer Vorfilter** (`prefilters.keywords`, Modul `prisma/prefilters.py`): neuer Grund `PREFILTER_KEYWORD`, eingereiht
   wie die bestehenden Vorfilter (Sprache, Jahr, Typ) - läuft vor dem Modell, ohne Tokenkosten, markiert statt zu löschen.
   - Durchsuchter Text: Title, Abstract, `keywords` und `keywords_mesh` als ein Text (Teilstring-Vergleich, standardmässig ohne
     Gross-/Kleinschreibung).
   - `exclude_any`: Treffer schliesst aus. `include_any`: Datensatz wird ausgeschlossen, wenn **keiner** der Begriffe vorkommt
     (Positivliste, wie `language.allow`). Beide leer = Filter aus. Sind beide gesetzt, hat `exclude_any` Vorrang (konsistent mit der
     Reihenfolge Sprache -> Jahr -> Typ -> Stichwort in `mark_prefilters`).
   - `on_missing` wie bei den anderen Filtern: `pass` (Standard) oder `exclude`, wenn Title, Abstract und beide Keyword-Felder leer sind.
2. **Optionaler Prompt-Kontext** (`screening.include_keywords_in_prompt`, Standard `false`): Das Modell sieht zusätzlich die
   Stichwörter im `<record>`-Block (`PromptBuilder.build(title, abstract, keywords)`). Da `keywords` Teil des variablen Datensatz-Teils
   ist, ändert sich der **stabile Prompt-Hash nicht**; wohl aber geht die Einstellung selbst in den Lauf-Fingerabdruck ein
   (`fingerprint_parts`), damit ein Wechsel während eines Laufs die Fortsetzung verweigert (E204) statt stillschweigend uneinheitliche
   Datensätze zu erzeugen.
3. Die Kostenschätzung (`services/cost.estimate_project`) zählt die Stichwörter nur mit, wenn der Schalter an ist (reines
   Text-Anhängen vor der Zählung, keine Änderung an `cost/estimator.py`).
4. Keine Schema-Version-Änderung: `keywords`/`keywords_mesh` sind bereits Spalten von `records.csv`; neu ist nur der
   Ausschlussgrund `PREFILTER_KEYWORD` im Katalog (`records_store.EXCLUSION_REASONS`, `prisma/reasons.py`).

## Folgen
* `config/models.py`: neues `KeywordFilter`-Modell unter `Prefilters.keywords`; neues Feld `ScreeningOptions.include_keywords_in_prompt`.
* UI-Einstellungsformular zeigt nur `include_any`/`exclude_any` (Listenfelder); `case_sensitive` bleibt wie `year`/`publication_types`
  ein projektdatei-only Feld (kein Oberflächenfeld), weil ein Bool-Feld unter einem standardmässig leeren optionalen Block in der
  Oberfläche nicht zuverlässig als "gesetzt" erkannt werden kann (gleiche Einschränkung besteht schon für `year.on_missing` usw.).
