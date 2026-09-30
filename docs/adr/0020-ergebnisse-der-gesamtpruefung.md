# ADR 0020: Ergebnisse der Gesamtprüfung - Entscheide zu Sperre, Ereignissen, Dedup und Fehlerbehandlung

Status: Angenommen als Umsetzungsentscheid des Agenten (2026-10-01); die mit *Bestätigung offen* markierten Punkte warten auf die Projektleitung

## Ausgangslage
Auf Wunsch der Projektleitung wurde der gesamte Code (Import, Projektordner, Dienste, PRISMA, Kosten, Befehlszeile) von drei unabhängigen Prüfern gelesen. Sie fanden echte Fehler
(verlorene Daten, verwechselte Zahlen, rohe Python-Fehler statt Fehlercodes). Die Behebungen stehen im CHANGELOG; dieser Eintrag hält nur die **Entscheide** fest, die das Verhalten
ändern und deshalb nachvollziehbar bleiben sollen.

## Entscheidungen
1. **Sperre im Zweifel "in Benutzung".** Lässt sich die Sperrdatei nicht lesen (Virenscanner, Herzschlag-Umschreibung), gilt sie als lebendig, nie als veraltet. Nur eine
   fehlerhafte oder nicht als UTF-8 lesbare Datei gilt als veraltet. Das Entfernen einer veralteten Sperre geschieht atomar (umbenennen, Token prüfen, fremde Sperre zurücklegen)
   und nur über den neuen Befehl `crapai unlock`, der nachfragt.
2. **Anhängende Dateien schneiden einen abgerissenen Schluss ab.** Bricht ein Schreibvorgang mitten in einer Zeile ab, wird der Rest vor dem nächsten Anhängen entfernt
   (er war nie ein vollständiger Eintrag; Leser ignorieren ihn ohnehin). Das gilt für das Import-Protokoll und `events.jsonl`.
3. **Flusszahlen nur aus gleich alten Momentaufnahmen.** Duplikate kommen allein aus den Dedup-Ereignissen, nie aus "Importsumme minus Stand nach Dedup". Ist ein Schritt veraltet
   (Import nach dem letzten Dedup; Dedup nach Vorfilter oder Gültigkeit), wird er gemeldet (`STALE_*`), und veraltete Vorfilter- und Gültigkeitszahlen werden **nicht** abgezogen.
   Ein Screening-Lauf ersetzt den früheren Lauf derselben Phase, statt ihn zu verdoppeln.
4. **Unveränderte Momentaufnahmen werden nicht erneut geschrieben**, solange seit der letzten kein Import und kein geändertes Dedup kam. Wiederholtes `crapai check` lässt `events.jsonl`
   nicht wachsen.
5. **Ein Ereignis, das nicht geschrieben werden kann, ist eine Warnung (Rückgabecode 4), kein Abbruch.** Die Datensätze sind die Quelle der Wahrheit; das Ereignis lässt sich durch
   erneutes `crapai check` nachtragen.
6. **`crapai check` hält eine Sperre für Dedup, Vorfilter, Gültigkeit und das anschliessende Lesen**, damit der Bericht nie zwei Zustände des Projekts mischt.
7. **Kurze Titel identifizieren keine Studie.** Ein Titel mit weniger als 4 Wörtern (`dedup.min_title_words`, 1 = aus) gleicht nie allein über den Titel ("Editorial", "Erratum");
   DOI und PMID gleichen weiterhin. *Bestätigung offen:* der Wert 4 ist ein Arbeitswert.
8. **Unbekannte Sprachmarken sind "fehlend".** `und`, `mul`, `zxx`, `unk`, `nan` sagen nichts über die Sprache; `on_missing` entscheidet. Ländercodes wie `en-US` sind Englisch.
9. **Preisliste: das jüngste bereits gültige `valid_from` gewinnt**, unabhängig von der Zeilenreihenfolge; Semikolon-getrennte Dateien (Excel, deutsche Einstellung) werden gelesen.
10. **Export schützt vor Tabellenformeln.** CSV und XLSX schreiben Zellen, die wie eine Formel beginnen, als Text (`'` davor); `--raw` schaltet das ab. `records.csv` selbst bleibt unverändert.
11. **Nicht-UTF-8-Dateien werden sichtbar.** Wird eine Importdatei als cp1252 oder latin-1 gelesen, steht das als Hinweis in der Ausgabe und im Protokoll.

## Bewusst nicht geändert
* `Retraction of Publication` (NBIB) markiert die Rückzugsmitteilung als zurückgezogen. Das ist gewollt: Die Mitteilung ist keine Studie, die gescreent werden soll.
* `enums.py` enthält ungenutzte Aufzählungen aus dem Vorgänger (`Framework`, `LLMProvider`, ...). Persistierte Namen werden nicht ohne Rückfrage geändert; sie bleiben, bis M3 klärt, welche gebraucht werden.
* CI installiert `tiktoken` nicht; der exakte OpenAI-Zähler ist mit einem Ersatzmodul getestet, nicht gegen das echte Paket.
