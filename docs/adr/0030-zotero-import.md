# ADR 0030: Zotero-Import (nur lesend: Bibliothek/Sammlung → Projekt)

Status: Angenommen (Entscheid der Projektleitung im Chat, 2026-10-02)

## Ausgangslage

Auf die Frage, was für eine Literaturrecherche-Software noch wichtig wäre, wurde u. a. eine
Zotero-Anbindung genannt. Recherche vorab: Zotero hat eine gut dokumentierte, erreichbare
Web-API (`api.zotero.org`), die auf Wunsch Treffer direkt als **RIS- oder BibTeX-Text** liefert -
also genau die Formate, die dieses Projekt schon lesen kann. Ein Lese-Zugriff (Bibliothek oder
Sammlung abrufen) lässt sich damit risikoarm in die bestehende Import-Pipeline einfügen. Ein
**Schreibzugriff** (Ein-/Ausschlussentscheidungen als Tags zurück nach Zotero schreiben) ist
deutlich aufwendiger (Versions-basierte Nebenläufigkeitskontrolle, Schreibrechte) und wird hier
bewusst **nicht** gebaut.

## Entscheidung

1. **Nur Lesen in dieser Runde.** `crapai zotero-import` holt Datensätze, schreibt aber nie etwas
   nach Zotero zurück. Ein Zurückschreiben wäre eine eigene, spätere Entscheidung.
2. **Keine neue Lese-/Parse-Logik.** Der von Zotero geholte RIS-/BibTeX-Text wird als echte Datei
   unter `sources/` abgelegt (`zotero-<library_id>-<Zeitstempel>.ris`/`.bib`) und danach ganz
   normal über die bestehende `services.importing.import_source()` eingelesen - Hash-
   Protokollierung (`E106`), Sicherung und Importprotokoll funktionieren unverändert mit, ohne
   eigene Parallel-Logik.
3. **Keine eigene "schon synchronisiert"-Markierung.** Ein erneuter Sync liefert praktisch nie
   byte-identischen Text (Reihenfolge/Zeitstempel ändern sich), `E106` würde also so gut wie nie
   greifen. Das ist unschädlich: die bestehende Duplikat-Erkennung (`crapai dedup`, DOI/Titel)
   markiert erneut importierte, bereits bekannte Datensätze ganz normal als `DUPLICATE`.
4. **Kein zweites Tor wie beim Jev-Vorfilter (ADR 0029).** `ZoteroSettings` hat keinen
   `enabled`-Schalter: der Import läuft nie automatisch, nur über den eigenen Befehl `crapai
   zotero-import` (oder die eigene GUI-Aktion) - ein zweites Tor hätte hier keinen Zweck, den es
   schützen müsste.
5. **Synchroner HTTP-Client**, anders als beim asynchronen `JevClient` (ADR 0029): ein
   Zotero-Abruf ist eine einzelne, allenfalls paginierte Folge von GET-Anfragen ohne
   Parallelitätsbedarf, ein `asyncio.run()`-Gerüst wäre hier nur unnötige Komplexität.
6. **Wiederverwendete Fehlerklassen.** `AuthError`/`RateLimited`/`TransientError`/`ImportFailed`
   aus `errors.py` werden unverändert wiederverwendet (401/403, 429, 5xx/Timeout, 404/leer) - sie
   sind generische HTTP-Ausgangs-Klassen, nicht spezifisch für ein Sprachmodell, trotz des
   `llm`-ähnlichen Vorbilds (`JevClient`).
7. **Kein neuer Menüpunkt in der Oberfläche.** Auf der bestehenden Daten-Seite ein zusätzlicher,
   eingeklappter Abschnitt "Oder: von Zotero importieren" - konzeptionell ist dies nur eine
   weitere Quelle für denselben Importschritt.

## Folgen

* Neues Paket `src/crapai/zotero/` (`client.py`: `ZoteroClient`, `MockZoteroClient`).
* Neues Extra `zotero = ["httpx"]` (gleiche Bibliothek wie beim Jev-Vorfilter, eigener Name je
  Fähigkeit).
* `src/crapai/config/models.py`: neues Modell `ZoteroSettings`, neues Feld `zotero` in
  `ProjectConfig` (kein `enabled`-Schalter, siehe Punkt 4).
* Neue Datei `src/crapai/services/zotero_import.py` (`zotero_import_project`, `build_client`).
* `src/crapai/cli.py`: neuer Befehl `crapai zotero-import`.
* Oberfläche: Daten-Seite (neuer Abschnitt), Einstellungen-Seite (neuer Abschnitt `zotero`).
* Zurückgestellt (bewusst nicht Teil dieser Runde): Zurückschreiben von Entscheidungen als Tags
  nach Zotero; ein lokaler Zotero-Connector (nur die Web-API, kein `localhost:23119`); eine
  eigene "bereits synchronisiert"-Markierung (die bestehende Duplikat-Erkennung genügt, siehe
  Punkt 3).
