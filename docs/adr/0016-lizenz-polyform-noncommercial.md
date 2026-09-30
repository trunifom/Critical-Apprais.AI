# ADR 0016: Lizenz des Codes - PolyForm Noncommercial 1.0.0

Status: Angenommen (Entscheid der Projektleitung, 2026-09-30; die Wahl der konkreten Lizenz trifft der Agent im Auftrag)

## Ausgangslage
Der Projektantrag sieht eine frei zugängliche Software vor. Weil die Entwicklung mit kantonalen Mitteln finanziert wird, soll die
**kommerzielle Nutzung ausgeschlossen** werden.

## Entscheidung
Der Code steht unter der **PolyForm Noncommercial License 1.0.0** (SPDX: `PolyForm-Noncommercial-1.0.0`, Text unverändert in `LICENSE`).

Was sie erlaubt: Nutzen, Kopieren, Verändern und Weitergeben für **jeden nicht kommerziellen Zweck**. Ausdrücklich zulässig sind Forschung,
Lehre und persönliche Nutzung sowie die Nutzung durch Hochschulen, öffentliche Forschungseinrichtungen, Gesundheits- und gemeinnützige
Organisationen und Behörden, **unabhängig von der Herkunft der Finanzierung**. Sie enthält eine Patentlizenz und verlangt, dass Kopien die
Lizenz und die Zeilen `Required Notice:` mitführen. Wer die Software kommerziell nutzen will (Firmenprodukt, Dienstleistung gegen Entgelt),
braucht eine eigene Vereinbarung mit den Rechteinhabern.

## Wichtig: Das ist keine Open-Source-Lizenz im Sinn der OSI
Die Open Source Definition verbietet Einschränkungen nach Verwendungszweck. Eine Lizenz, die kommerzielle Nutzung ausschliesst, ist daher
**"source available"**: der Quelltext ist offen einsehbar und frei nutzbar für nicht kommerzielle Zwecke, aber nicht "Open Source" im engen Sinn.
Im Projektantrag und in Veröffentlichungen sollte deshalb von "frei zugänglich" oder "quelloffen für nicht kommerzielle Nutzung" gesprochen werden.

## Alternativen
| Lizenz | Kommerzielle Nutzung | Bemerkung |
|---|---|---|
| **PolyForm Noncommercial 1.0.0** (gewählt) | ausgeschlossen | für Software geschrieben, klar formuliert, nennt Hochschulen und Behörden ausdrücklich |
| CC BY-NC-SA 4.0 | ausgeschlossen | von Creative Commons selbst nicht für Software empfohlen (keine Patentklausel, unklare Weitergabe von Quelltext) |
| AGPL-3.0 | erlaubt, aber Quelltext-Pflicht auch für Netzdienste | echte Open-Source-Lizenz; verhindert das geschlossene Weiterverkaufen, nicht die kommerzielle Nutzung |
| MIT / Apache-2.0 | erlaubt | offenste Variante; passt nicht zum Wunsch, Kommerzielles auszuschliessen |

## Geltungsbereich und offene Punkte
* Die Lizenz gilt für den **eigenen Code und die eigene Dokumentation** des Projekts. Nicht davon erfasst sind Fremdmaterialien im Repository
  (`docs/literature/`, `docs/guidelines/`, `docs/reports/`, `docs/swissgpt/`, `reference/`, `tests/data/`, `tests/data_large/`); dafür gelten die Rechte der jeweiligen Urheber.
  Der Ausschnitt `reference/` ist ein Snapshot des Vorgängers und wird nicht lizenziert, sondern nur mitgeführt.
* **Zu klären durch die Projektleitung (rechtlich, nicht technisch):** ob die ZHAW oder der Fördergeber Rechte am Vorgänger und am neuen Code hat
  und wer als Rechteinhaber in der Zeile `Required Notice` stehen soll. Aktuell steht dort neutral "the Critical Apprais.AI authors".
  Diese Wahl ist keine Rechtsberatung; sie sollte von der Rechtsabteilung der Hochschule bestätigt werden.
* Fremdmaterial vor einer öffentlichen Veröffentlichung prüfen oder ausschliessen (siehe README).
* Abhängigkeiten behalten ihre eigenen Lizenzen; sie sind nicht Teil dieses Repositorys.

## Folgen
* Datei `LICENSE` (Text der Lizenz plus `Required Notice`), Feld `license` in `pyproject.toml`, Hinweise in README, CHANGELOG, Entwickler- und Benutzerdokumentation.
* `tests/unit/test_license.py` prüft, dass der Lizenztext unverändert bleibt.
* Ein späterer Wechsel zu einer anderen Lizenz ist nur mit Zustimmung aller Rechteinhaber möglich; früher verteilte Kopien bleiben unter der alten Lizenz.
