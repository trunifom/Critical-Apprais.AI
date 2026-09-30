# ADR 0013: GUI-Framework Streamlit

Status: Angenommen (Entscheid der Projektleitung, 2026-09-30)

## Entscheidung
Die lokale Oberfläche wird mit **Streamlit** gebaut (`sara ui`). Lange Läufe laufen im getrennten Worker-Prozess (ADR 0006); die UI liest nur Projektdateien.

## Alternativen
Flet (die übernommenen Coding-Guidelines des Vorgängers setzen es voraus), NiceGUI/FastAPI, PySide6, Excel-Modus. Nicht gewählt.

## Folgen
- Vorgaben für Streamlit siehe Plan Kap. 27.9 (lokaler Server nur auf 127.0.0.1, Fragment-Aktualisierung, kein nativer Ordnerdialog -> Pfadfeld + Hilfsdialog).
- Kern und CLI bleiben GUI-unabhängig (Schichtregel), sodass ein späterer Wechsel möglich bleibt.
- Die Flet-Bezüge in `docs/coding/coding_guidelines.original.md` sind gegenstandslos.
