# ADR 0019: Deterministische Vorfilter - Reihenfolge, Gründe, fehlende Metadaten

Status: Angenommen als Umsetzungsentscheid des Agenten (2026-09-30); ergänzt ADR 0018

## Ausgangslage
Eine Forschungsgruppe stellte fest, dass das Modell die Sprache von Studien nicht zuverlässig erkennt (Plan Kap. 35.4, U3). Metadaten wie Sprache, Jahr und
Publikationstyp werden deshalb im Code geprüft, **vor** dem Modell, ohne Tokenkosten. Die Datensätze werden wie immer markiert und nie gelöscht.

## Entscheidung
1. **Neue Gründe** `PREFILTER_LANGUAGE`, `PREFILTER_YEAR`, `PREFILTER_TYPE` (vom Plan in Kap. 35.4 vorgesehen; Katalog in `records.csv` erweitert, bestehende Werte
   unverändert). Wenn mehrere Filter zutreffen, gilt der erste in der Reihenfolge Sprache, Jahr, Typ; `exclusion_details` nennt alle.
2. **Reihenfolge:** Import, Dedup, **Vorfilter**, Gültigkeit (ADR 0018 nannte Import, Dedup, Gültigkeit). Der Plan nennt die Abstract-Prüfung vor den Vorfiltern; für das
   Ergebnis ist das gleichwertig, weil die Vorfilter Gültigkeitsgründe ersetzen dürfen, so wie Duplikate es tun. Damit hat ein französischer Datensatz ohne Abstract den
   aussagekräftigeren Grund `PREFILTER_LANGUAGE`. Dedup darf Vorfilter- und Gültigkeitsgründe ersetzen; die Vorfilter ersetzen nie `DUPLICATE`, `EMPTY_RECORD`,
   `IMPORT_ERROR`; die Gültigkeitsprüfung ersetzt nie einen Vorfiltergrund. `crapai check` führt die Schritte in dieser Reihenfolge aus.
3. **Fehlende Metadaten:** Ein Filter wirkt nur auf vorhandene Angaben. Fehlt die Angabe, entscheidet `on_missing`: `pass` (Standard, der Datensatz geht ans Modell)
   oder `exclude`. Ein nicht erkennbarer Sprachtext ("n/a", "see text") zählt als fehlend. Die Zahl der Datensätze, die nur wegen fehlender Angaben durchgelassen
   wurden, wird gemeldet (`passed_on_missing`).
4. **Sprache:** Vergleich über ISO-639-2-Codes (`de`, `deu`, `ger`, `German` sind gleich); mehrere Sprachen in einem Datensatz: erlaubt, wenn mindestens eine erlaubt ist.
   Die Namenstabelle in `prisma/prefilters.py` deckt die üblichen Sprachen ab; unbekannte dreibuchstabige Codes werden unverändert verglichen.
5. **Publikationstyp:** ausgeschlossen, wenn **irgendein** Typ des Datensatzes in der Ausschlussliste steht (Gross-/Kleinschreibung und Leerzeichen egal, ganzer Typ,
   kein Teilwort). Ein Datensatz "Journal Article; Editorial" wird also mit `Editorial` in der Liste ausgeschlossen. *Abweichung vom Plan: der Plan sagt nichts zu
   mehreren Typen; diese Lesart ist strenger und sollte bestätigt werden.*
6. **Zurückgezogene Studien** bleiben bei der Gültigkeitsprüfung (`exclude_retracted`, ADR 0018); im PRISMA-Fluss zählen sie zusammen mit den Vorfilter-Ausschlüssen
   unter "vor dem Screening aus anderen Gründen entfernt".

## Folgen
* Neue Module `prisma/prefilters.py`, `services/prefilter.py`; `crapai check` ruft `prefilter_project` zwischen Dedup und Gültigkeit auf.
* Ereignis `INFO` mit `kind: prefilter` (Momentaufnahme), das der Fluss als "andere Gründe" zählt.
* Unterschied zu `on_missing: exclude`: das Plan-Dokument beschreibt nur `pass`; `exclude` ist eine Annahme dieser Umsetzung.
