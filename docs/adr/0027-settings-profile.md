# ADR 0027: Wiederverwendbare Settings-Profile

Status: Angenommen als Umsetzungsentscheid des Agenten (2026-10-02); Auftrag der Projektleitung im Chat, zusammen mit ADR 0026 (Volltext-Screening) und zusätzlichen Export-Formaten

## Ausgangslage

Die Projektleitung wünschte, Einstellungen eines Projekts (Kriterien, Ziele, Screening-Einstellungen, Modellwahl) als benannte Vorlage zu speichern und in ein anderes (oder neues) Projekt zu laden - zum Beispiel eine bewährte Kriterienliste und Modellkonfiguration für mehrere ähnliche Reviews wiederzuverwenden. Dafür gibt es **keinen Plankapitel**: Das Vorhaben ist neu, ausserhalb der ursprünglichen Spezifikation, und musste sich darum an bestehende Muster anlehnen statt an einen vorgegebenen Entwurf.

## Entscheidung

1. **Ein Profil ist keine Kopie von `project.yaml`**: Es enthält nur die übertragbaren Teile - `objectives`, `criteria`, `screening` (inklusive der Volltext-Einstellungen aus ADR 0026) und `llm` (inklusive `api_key_env`, das nur den NAMEN einer Umgebungsvariable trägt, nie einen Schlüssel). Projekt-Titel, -Beschreibung, -Sprache, -Modus sowie alles Betriebliche (`run`, `limits`, `dedup`, `prefilters`, `quality`, `discussion`, `acknowledgements`, `import`) gehören nicht zu einem Profil - sie sind projekt- bzw. laufspezifisch, nicht Teil des "Review-Designs".
2. **Profile leben ausserhalb jedes Projekts**, im Benutzerordner (`~/.config/crapai/profiles/<name>.yaml`, neben der schon vorhandenen optionalen `config.yaml` und der Oberflächen-Datei `ui_prefs.json`), damit sie projekt-, rechner- (bei synchronisiertem Ordner) und reviewübergreifend wiederverwendbar sind.
3. **Speichern** (`crapai profile save <projekt> <name>`) liest die **wirksame** Konfiguration des Projekts (`project.yaml` mit `project.overrides.yaml` darüber, wie `crapai config show` sie zeigt), nicht nur die rohe `project.yaml` - ein Profil spiegelt also, was ein Projekt gerade tatsächlich tut, inklusive über die Oberfläche geänderter Werte.
4. **Laden** (`crapai profile load <projekt> <name>`) schreibt die vier Abschnitte des Profils in `project.overrides.yaml` (`config.overrides`, ADR 0021) - genau wie `crapai config set` oder die Oberfläche es täten. **`project.yaml` wird nie verändert** (Kommentare bleiben erhalten); bereits vorhandene Overrides ausserhalb dieser vier Abschnitte bleiben unangetastet; das Ergebnis wird vor dem Schreiben validiert; rückgängig mit `crapai config reset`.
5. **Weitere Befehle**: `crapai profile list` (Namen aller gespeicherten Profile), `crapai profile show <name>` (Inhalt, auch als `--json`), `crapai profile delete <name>`.
6. **Eigenes, kleines Pydantic-Modell** `SettingsProfile` (eigene `schema_version`, da Profile und `project.yaml` unabhängig voneinander weiterentwickelt werden können), das die bestehenden Modelle `Criteria`, `ScreeningOptions`, `LlmSettings` aus `config.models` wiederverwendet statt sie zu duplizieren.

## Folgen

* Neues Modul `config.profiles` (`SettingsProfile`, `save_profile`, `load_profile`, `apply_profile`, `list_profiles`, `delete_profile`).
* Neue Befehle `crapai profile save/load/list/show/delete`.
* Oberfläche: Auswahl und Knöpfe "Als Profil speichern"/"Profil laden" auf der Einstellungen-Seite.
* Zurückgestellt (bewusst nicht gebaut): Profile für `dedup`/`prefilters`/`quality` (eher projekt- als reviewdesign-spezifisch); ein Export/Import von Profilen als teilbare Datei über den Benutzerordner hinaus (das Profil ist bereits eine eigenständige YAML-Datei und kann von Hand kopiert werden, das reicht für den geäusserten Bedarf).
