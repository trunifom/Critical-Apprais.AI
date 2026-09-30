# ADR 0018: Markieren statt Löschen - Ausschlussgründe, Reihenfolge und Vorsicht bei Duplikaten

Status: Angenommen als Umsetzungsentscheid des Agenten (2026-09-30); zwei Punkte warten auf die Bestätigung der Projektleitung (siehe unten)

## Ausgangslage
Ein Datensatz darf nie still verschwinden (goldene Regel 3). Mehrere Schritte begründen, warum ein Datensatz nicht an das Modell geht: Import
(`EMPTY_RECORD`, `IMPORT_ERROR`), Duplikaterkennung (`DUPLICATE`), Gültigkeitsprüfung (`NOT_SCREENABLE`, `RETRACTED`, `NO_ABSTRACT`). Ein Datensatz trägt
höchstens **einen** `exclusion_reason`. Die Schritte müssen sich einigen, wer wen ersetzen darf, sonst hängt das Ergebnis von der Reihenfolge ab und das
PRISMA-Diagramm (Duplikate zuerst) wäre falsch.

## Entscheidung
1. **Besitz der Gründe** (`prisma/reasons.py`): Import setzt `EMPTY_RECORD`/`IMPORT_ERROR`; Dedup setzt `DUPLICATE` und darf einen **Gültigkeitsgrund** ersetzen;
   die Gültigkeitsprüfung setzt `NOT_SCREENABLE`, `RETRACTED`, `NO_ABSTRACT` und ersetzt **nie** den Grund eines anderen Schritts. Ergebnis: dieselbe Endmarkierung
   in beiden Reihenfolgen; Sollreihenfolge ist Import, Dedup, Gültigkeit.
2. **Rangfolge innerhalb der Gültigkeit:** `NOT_SCREENABLE` vor `RETRACTED` vor `NO_ABSTRACT` (der spezifischere Grund gewinnt). Zurückgezogene Studien werden nur mit
   `exclude_retracted: true` ausgeschlossen; sonst bleiben sie im Lauf und sind über `is_retracted` sichtbar, damit sie nicht unbemerkt eingeschlossen werden.
3. **Duplikate im Zweifel nicht markieren** (Sensitivität zuerst): kein Vergleich leerer Titel; gleicher Titel bei **verschiedenen DOIs** ergibt kein Duplikat.
   Behalten wird der vollständigste Datensatz (Abstract, DOI, PMID), sonst der zuerst importierte.
4. **Qualitätsmerkmale ändern nie die Teilnahme:** `abstract_quality` (`ok`, `short`, `suspect_concat`) ist ein Hinweis für den Preflight.
5. Läufe sind **wiederholbar**: die Schritte berechnen ihre Markierungen bei jedem Aufruf neu (frühere Markierungen des Schritts werden zuerst entfernt).

## Abweichungen vom Plan und Grenzen (bitte prüfen)
* **`dedup_method = pmid`** wird für Treffer der Strategie `strict_ids` verwendet; Plan Kap. 26.1 nennt `doi`, `title_norm`, `title_authors`, `fuzzy`. *Bestätigung offen.*
* **Schwelle für "Wort zu lang" (`suspect_concat`) ist 40 statt 25 Buchstaben.** Der Plan nennt 25; in den Testdaten hat ein gewöhnliches deutsches Wort
  ("Verarbeitungsgeschwindigkeit") 28. Mit 40 werden im gesamten Testbestand (255 Abstracts) genau die zwei kaputten Abstracts erkannt, keine deutschen. Zusätzlich gilt eine
  mittlere Wortlänge über 9 (bei mindestens 30 Wörtern) als verdächtig. *Bestätigung offen.*
* **Nicht erfüllbar:** Die Karte T-M2-03 fordert, dass das Cochrane-Beispiel (Wörter wie "stressmanagement", "berecruited") als `abstract_suspect_concat` markiert wird. Die
  Wörter sind gewöhnlich lang; ohne Wörterbuch lassen sie sich von echten Wörtern nicht unterscheiden (die mittlere Wortlänge dieses Datensatzes liegt unter der eines anderen, intakten
  Cochrane-Abstracts). Ein Test hält diese Grenze fest. Der Plan selbst sagt, dass sich das "nicht zuverlässig reparieren" lasse.
* **Schwelle für `short`:** 20 Wörter ist ein Arbeitswert (Plan nennt keinen; kürzeste echte Abstracts der Testdaten: 18 und 2 Wörter).
* **Titel für `NOT_SCREENABLE`:** nur ganze Titel wie "Front matter", "Index", "Table of contents", "Cover" (Liste in `prisma/validity.py`, erweiterbar); Titel, die nur mit
  einem dieser Wörter beginnen ("Index of suspicion ..."), gelten als Studien.

## Folgen
* Neue Module `prisma/reasons.py`, `prisma/validity.py`, `services/validity.py`; Änderung in `prisma/dedup.py` (Ersetzen von Gültigkeitsgründen).
* `crapai check` (T-M2-04) ruft Dedup und Gültigkeit in der Sollreihenfolge auf.
* Das PRISMA-Diagramm zählt je Grund die markierten Datensätze; nichts wird gelöscht, alles bleibt in `records.csv` und in der Ergebnistabelle.
