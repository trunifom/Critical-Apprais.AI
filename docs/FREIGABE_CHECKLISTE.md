# FREIGABE_CHECKLISTE.md - Was vor einer öffentlichen Veröffentlichung auf GitHub erledigt sein muss

Stand: 2026-10-01. Diese Liste gilt für den Moment, in dem das Repository öffentlich wird (oder bleibt). Solange es privat ist, darf alles hier bleiben.

## 1. Fremdes und unveröffentlichtes Material entfernen

Diese Verzeichnisse enthalten Material, das nicht ohne Klärung veröffentlicht werden darf. Sie werden **am Ende** aus dem Repository genommen, nicht jetzt: Die Tests und die Übernahmen aus dem Vorgänger brauchen sie noch.

| Verzeichnis | Inhalt | Was tun |
|---|---|---|
| `reference/` | Schreibgeschützter Stand des Vorgängers (SARA-App, SARA-Vorläufer) | aus dem Repository löschen (`git rm -r reference`) |
| `tests/data/` | Beispieldateien aus Literaturdatenbanken (PubMed, Cochrane, Zotero-Exporte) | entfernen oder durch selbst erzeugte, frei verwendbare Testdaten ersetzen |
| `tests/legacy_runs/` | Läufe der alten SARA-App (Goldwerte) | entfernen |
| `tests/expected/` | Erwartungswerte, die aus den obigen Dateien berechnet wurden | neu aus den Ersatzdaten erzeugen oder entfernen |
| `docs/legacy/` | Handbuch und Unterlagen des Vorgängers | entfernen oder mit Erlaubnis übernehmen |
| `docs/swissgpt/` | API-Beschreibung von SwissGPT/AlpineAI | nur behalten, wenn die Weitergabe erlaubt ist |

**Auch aus der Git-Geschichte:** Löschen im neuesten Stand genügt nicht, die Dateien bleiben in früheren Commits lesbar. Vor der Veröffentlichung entweder ein **neues, sauberes Repository** ohne diese Dateien anlegen (empfohlen) oder die Geschichte bereinigen (`git filter-repo`). Das geschieht nur auf ausdrücklichen Wunsch des Projektleiters und nie mit `--force` auf dem bestehenden Repository ohne dessen Zustimmung.

Nach dem Entfernen müssen Tests, die diese Dateien brauchen, übersprungen oder ersetzt werden (`test_fixture_inventory`, `test_legacy_golden`, `test_import_service`, die Integrationstests, `test_prisma_flow` mit dem Vorgänger als Gegenprobe).

## 2. Lizenz und Rechteinhaber

* `LICENSE` nennt als Rechteinhaber Dominik Kunz, Dominique Truninger und die ZHAW (Zürcher Hochschule für Angewandte Wissenschaften). Ob die ZHAW der Veröffentlichung unter PolyForm Noncommercial zustimmt, ist mit der Hochschule zu klären (Rechtsdienst, Transfer- oder Bibliotheksstelle) und schriftlich festzuhalten.
* Die Lizenz ist **quelloffen im Sinn von "einsehbar", nicht im Sinn der Open-Source-Definition** (OSI), weil sie kommerzielle Nutzung ausschliesst. Das steht so im README und in ADR 0016.
* Abhängigkeiten prüfen: Jede verwendete Bibliothek hat ihre eigene Lizenz. `pip-licenses` (oder gleichwertig) ausführen und die Liste im README unter "Drittkomponenten" nennen.

## 3. Geheimnisse

* Im Repository und in der Geschichte dürfen keine API-Schlüssel, Tokens oder Zugangsdaten stehen. Suche: `git log -p | grep -i -E "sk-|api[_-]?key|token"` und ein Werkzeug wie `gitleaks`.
* Beispielprojekte enthalten keine echten Schlüsselnamen mit Werten (nur Namen der Umgebungsvariablen).

## 4. Qualität vor dem Veröffentlichen

* `python scripts/qa.py --ci` ist grün, die CI auf GitHub ist grün (alle drei Betriebssysteme).
* README, Handbuch und CHANGELOG stimmen mit dem Stand überein; der Haftungshinweis ("Ergebnisse sind Vorschläge") steht im README und in der Oberfläche.
* Live-Test gegen einen echten Anbieter einmal erfolgreich gelaufen (siehe Handbuch, Abschnitt Screening).
