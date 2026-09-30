# ADR 0017: Technische Namen - Kurzform CrAp-AI, Paket und Befehl `crapai`

Status: Angenommen (Entscheid der Projektleitung, 2026-09-30; die konkreten Bezeichner legt der Agent im Auftrag fest)

## Ausgangslage
Ordner, Paket, Befehl und Zustandsordner trugen Arbeitsnamen aus der Zeit vor dem Produktnamen (`SARA-Local`, `saralocal`, `sara`, `.sara/`). Sie erinnerten
an den Vorgänger, den die neue Software gerade nicht sein soll (`docs/NAMING_AND_HISTORY.md`). Die Projektleitung hat als Kurzform **CrAp-AI** bzw. **CrApAi**
vorgeschlagen und die Umbenennung ausdrücklich freigegeben.

## Entscheidung
| Bereich | Alt | Neu |
|---|---|---|
| Kurzform des Produkts | - | **CrAp-AI** (Texte); der volle Name **Critical Apprais.AI** bleibt massgebend |
| Python-Paket | `saralocal` | `crapai` |
| Distributionsname (`pyproject.toml`) | `sara-local` | `crapai` |
| CLI-Befehl | `sara` | `crapai` |
| Zustandsordner im Projekt | `.sara/` | `.crapai/` |
| Umgebungsvariablen für Einstellungen | `SARA_<ABSCHNITT>__<SCHLUESSEL>` | `CRAPAI_<ABSCHNITT>__<SCHLUESSEL>` |
| Benutzerkonfiguration | `~/.config/sara/config.yaml` | `~/.config/crapai/config.yaml` |
| Repository | - | bleibt `Critical-Apprais.AI` |

Hyphen und Grossbuchstaben sind in Python-Paketnamen nicht möglich; die Schreibweise `CrApAi` der Projektleitung ergibt in Kleinbuchstaben `crapai`.
Die Konstanten stehen an einer Stelle: `crapai/branding.py` (`SHORT_NAME`, `PACKAGE_NAME`, `CLI_NAME`, `STATE_DIR_NAME`, `ENV_PREFIX`).

## Was nicht umbenannt wurde
* Der **Vorgänger** heisst weiter SARA / SARA-App: `reference/`, `docs/legacy/`, `docs/reports/`, archivierte Läufe und Berichte, Kommentare `PORTED from SARA-App`.
* **Persistierte Namen** des Datenvertrags (Spalten, Enum-Werte, JSON-Schlüssel) wurden nie nach dem Produkt benannt und bleiben unverändert.
* Die Anbieter-Umgebungsvariablen (`SWISSGPT_API_KEY` u. a.) sind anbieterbezogen.

## Folgen
* **Datenvertrag `.sara/` → `.crapai/`:** Projekte, die vor dieser Umbenennung angelegt wurden, haben noch `.sara/`. Es gibt noch keine produktiven Projekte; `Workspace.open` erkennt
  den alten Ordner und erklärt die Umbenennung von Hand (Fehler E404 mit Hinweis). Die Schema-Version bleibt 1.
* Der Kern-Befehl erscheint in allen Hilfetexten, Meldungen (`cli.status.no_records` u. a.), im Benutzerhandbuch und im Plan als `crapai ...`.
* Das Wort "crap" bedeutet im Englischen "Mist". Der Name ist ein bewusster Scherz; für Suche, Veröffentlichungen und offizielle Kommunikation gilt der volle Name.
  Ändert sich die Einschätzung, ist ein weiterer Wechsel jetzt noch billig (eine Konstante plus Umbenennung), später nicht mehr.
