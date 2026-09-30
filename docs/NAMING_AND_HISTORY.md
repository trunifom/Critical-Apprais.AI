# NAMING_AND_HISTORY.md - Name, Vorgeschichte und Namensregeln

**Kurz:** Die neue Software heisst **Critical Apprais.AI**. Es hat früher eine Software namens **SARA** gegeben
(Prototyp, ZHAW). Critical Apprais.AI ist **nicht SARA**, sondern eine neue, lokale Software mit demselben fachlichen Ziel.
Der Ordner, das Python-Paket und der Kommandozeilenbefehl tragen noch die **vorläufigen Arbeitsnamen** `SARA-Local`,
`saralocal` und `sara` (siehe Abschnitt 4).

## 1. Genealogie

| Stufe | Name | Was es ist | Wo es liegt | Stand |
|---|---|---|---|---|
| 1 | **SARA** (Smart Artificial Review Assistant/Assistance) | Erster Forschungsprototyp: Python-Bibliothek ohne Oberfläche, LLM-Aufrufe (OpenAI, später SwissGPT/Anthropic), Unit-Tests | lokal `GitHub/SARA`, Remote `github.zhaw.ch/hirsch-lab/SARA` | Vorgänger, Snapshot in `reference/sara-ancestor/` |
| 2 | **SARA-App** | Web-Anwendung: Streamlit + Supabase (Datenbank, Login, Storage) + Hintergrund-Worker mit E-Mail-Versand. Gefördert vom ZHAW *Digital Futures Fund 2024*; Abschlussbericht 2025 mit Evaluation und Usability-Tests | lokal `GitHub/SARA-App`, Remote `github.com/domkuzz/SARA-App` | Vorgänger, Snapshot in `reference/sara-app/` |
| 3 | **Critical Apprais.AI** | **Die neue Software.** Läuft komplett lokal, keine Datenbank, kein Server, keine Konten; Streamlit-Oberfläche und CLI; Ergebnisse als CSV/XLSX im Projektordner; künftig vorwiegend SwissGPT | dieser Ordner | in Planung/Aufbau |

Das Projekt hiess "SARA" und ist mit dem Abschlussbericht (`docs/reports/`) und den beiden Repositories dokumentiert. **Aus der Sicht des
neuen Projekts ist SARA Geschichte**: Man lernt daraus (Plan Kap. 2, 3, 35), übernimmt geprüfte Bausteine (`docs/MIGRATION.md`) und
liest die alten Testdaten, aber man baut kein "SARA 2".

## 2. Was von SARA bleibt und was nicht

| Bleibt (fachlich) | Bleibt nicht |
|---|---|
| Ziel: Titel-/Abstract-Screening mit LLM als "digitaler Peer" (zweite Bewertung), mit Begründung je Entscheidung | Name, Logo und Auftritt "SARA" |
| PRISMA-Nachvollziehbarkeit, nicht-destruktive Markierung, `study_uid` | Supabase, Login/Konten, E-Mail-Benachrichtigung, Server-Deployment |
| Kriterien-Frameworks (PICOS, SPIDER, PECO, PIRD, CUSTOM) | Der Code der App als Ganzes (nur ausgewählte Bausteine, `docs/MIGRATION.md`) |
| Evaluationsmethodik (Test-Retest, Interrater, Sensitivität als Hauptmass) | Bekannte Fehler des Prototyps (Plan Kap. 3, L1-L18) |
| Lehren aus den Usability-Tests (Plan Kap. 35.4) | |

## 3. Namensregeln (verbindlich für Menschen und Agenten)

1. **Produktname:** exakt **Critical Apprais.AI** (grosses C, grosses A, Punkt, grosses AI). Kein "CriticalApprais", kein "Critical Appraisal AI"
   ohne Absprache.
2. **Das neue Produkt wird nie "SARA" genannt** - nicht in der Oberfläche, in Hilfetexten, Berichten, Methodentexten, Manifesten, Dateikopfzeilen
   oder in der README. Im Code steht der Anzeigename in **einer** Konstante (`saralocal/branding.py: PRODUCT_NAME`), nicht verstreut.
3. **"SARA" ist erlaubt** nur für das Vorgängerprojekt: in `docs/legacy/`, `docs/reports/`, `reference/`, Kommentaren wie `PORTED from SARA-App`,
   Kapiteln über die Vorgeschichte, und in **archivierten Daten** (Lauf-Dateien, Berichte in `tests/legacy_runs/`, `tests/expected/`). Diese Dateien werden
   nicht umbenannt.
4. **Schreibweise für Vorgänger:** "SARA" (Vorgänger-Prototyp), "SARA-App" (Web-Anwendung). Wer "SARA" sagt, meint nie die neue Software.
5. **Persistierte Namen** (Spaltennamen, Enum-Werte, `study_uid`) bleiben unverändert, auch wenn sie aus SARA stammen: Sie sind Datenverträge
   (`AGENTS.md`, Regel 4), keine Markennamen.
6. **Nutzertexte** (i18n): kein "SARA". Der Zweck-Text auf der Startseite nennt Critical Apprais.AI.
7. Wer im Bestand auf "SARA" in einem Nutzertext des **neuen** Codes stösst (z. B. in aus `reference/` kopierten Texten), ersetzt es durch `PRODUCT_NAME`.

## 4. Vorläufige Arbeitsnamen (technische Bezeichner)

Die technischen Namen wurden angelegt, bevor der Produktname feststand. Sie bleiben **vorläufig unverändert**, damit Code, Tests und Doku
konsistent bleiben. Agenten benennen sie **nicht auf eigene Faust um**. Die Umbenennung ist eine eigene Aufgabe (`tasks/T-M0-03.md`).

| Bezeichner | Heute (Arbeitsname) | Wo | Hinweis |
|---|---|---|---|
| Ordner / Starterpaket | `SARA-Local` | `C:\Users\trug\Documents\GitHub\SARA-Local` | wird zum Repository-Namen |
| Python-Paket | `saralocal` (`src/saralocal/`) | Importe in Code und Tests | Bindestrich/Punkt sind in Paketnamen nicht möglich |
| Projektname in `pyproject.toml` | `sara-local` | | |
| CLI-Befehl | `sara` (`sara import`, `sara screen`, ...) | Plan Kap. 15, 27.10, 31 | Kurzer Befehl nötig; Vorschlag in T-M0-03 |
| Zustandsordner im Review-Projekt | `.sara/` | Plan Kap. 6 | Teil des Dateiformats -> vor v1 endgültig festlegen |
| Umgebungsvariablen | `SWISSGPT_API_KEY` u. a. | `templates/` | anbieterbezogen, nicht produktbezogen |

Wo der Plan "SARA-Local" schreibt, meint er den **Projekt-/Ordnernamen** (Arbeitsname) oder, in Prosa, die neue Software. Im Text wurde der Produktname
`Critical Apprais.AI` dort eingesetzt, wo die Software gemeint ist. Befehle wie `sara screen` sind Platzhalter für den künftigen CLI-Namen.

Optionen für die endgültigen Bezeichner (Entscheid offen, Aufgabe T-M0-03): Paket `criticalapprais` oder `apprais_ai`; CLI `apprais` oder `capprais`;
Ordner/Repo `Critical-Apprais-AI`; Zustandsordner `.apprais/`. Punkt und Grossbuchstaben im Produktnamen sind für Paket- und Befehlsnamen nicht verwendbar.

## 5. Wörterbuch alt -> neu (für Leser der alten Dokumente)

| Begriff in alten Dokumenten | Bedeutung heute |
|---|---|
| SARA | Vorgängerprojekt/Prototyp (Bibliothek) |
| SARA-App, "die App" | Streamlit-/Supabase-Web-Anwendung, Vorgänger |
| SARA-Local | Arbeits-/Ordnername der neuen Software Critical Apprais.AI |
| `sara_statistics` | Alte Auswertungsskripte; Logik in `saralocal/legacy.py` und später `stats/` übernommen |
| "SARA-Ergebnis", "SARA-Lauf" | Ergebnisdatei bzw. Lauf der SARA-App (archiviert in `tests/legacy_runs/`) |
| "digitaler Peer" / "digitaler Assistent" | Leitidee bleibt: KI als zweite Bewertung, Menschen entscheiden |
| Digital Futures Fund (DFF) | Förderprogramm des Vorgängerprojekts |

## 6. Wie Agenten damit umgehen

- `AGENTS.md` nennt Produkt und Vorgeschichte in Abschnitt 1.
- Beim Schreiben von Nutzertexten, README-Abschnitten, Berichten: `PRODUCT_NAME` verwenden.
- Beim Lesen von `reference/` und `docs/legacy/`: Diese Materialien beschreiben SARA. Nicht mit dem neuen Produkt verwechseln.
- Unsicher, ob ein Name Marke oder Datenvertrag ist? Datenvertrag gewinnt (nicht ändern) und im PR/Bericht anmerken.
