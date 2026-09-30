# reference/ - Snapshots des alten Codes (nur lesen)

Diese Ordner enthalten **unveränderte Kopien** von Code aus früheren Projekten. Sie sind Vorlage und Nachschlagewerk,
**kein Teil der Anwendung**.

- **Nicht bearbeiten** (Änderungen gehören nach `src/saralocal/`, mit Kopfzeile `PORTED from ...`).
- **Nicht importieren** (der Code hängt von Streamlit/Supabase/`st.secrets` ab und läuft hier nicht).
- Welche Datei wohin gehört und ob sie schon portiert ist: `docs/MIGRATION.md`.

| Ordner | Herkunft | Stand |
|---|---|---|
| `sara-app/` | `SARA-App` (Streamlit + Supabase), lokales Repo `GitHub/SARA-App` | Commit in `sara-app/SOURCE_COMMIT.txt` (Branch `usertesting`) |
| `sara-ancestor/` | `SARA` (Vorgänger, ZHAW-GitHub `hirsch-lab/SARA`), lokales Repo `GitHub/SARA` | Commit in `sara-ancestor/SOURCE_COMMIT.txt` |

## Bekannte Mängel im Snapshot (nicht übernehmen)

Siehe `docs/PROJEKTPLAN.md` Kapitel 3 (L1-L18). Kurz: Label-Regel `XXX -> 0, sonst 1` (L4), Retry wirkungslos (L2),
sequentielle Verarbeitung (L3), RIS-Tag-Filter verwirft Fortsetzungszeilen (L15), Streamlit-Abhängigkeit im Parser (L16).

## Datenschutz-Hinweis

`sara-app/sara_statistics/src/inter_rater_reliability.py` enthält einen festen Pfad in ein persönliches OneDrive
(Benutzername). Der Pfad ist nur Referenz; im neuen Code darf kein Benutzerpfad stehen.
