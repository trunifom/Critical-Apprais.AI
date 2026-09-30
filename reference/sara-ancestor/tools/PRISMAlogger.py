"""
===========================================================
Log-Handler für PRISMA-Prozess
===========================================================

Speichert alle Schritte als:
✅ JSON (detaillierte Infos)  
✅ CSV (kompakte Übersicht)  

Author: Dominique Truninger  
Version: 1.0  
"""

import json
import csv
from datetime import datetime

LOG_ENTRIES = []

def log_event(step, message, count=None):
    """
    Speichert einen Log-Eintrag im globalen Log-Speicher.

    :param step: Prozessschritt (z.B. "Title/Abstract Screening")
    :param message: Log-Nachricht
    :param count: Anzahl der betroffenen Studien (optional)
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "timestamp": timestamp,
        "step": step,
        "message": message,
        "count": count
    }
    LOG_ENTRIES.append(entry)
    print(f"[LOG] {timestamp} - {step}: {message}")

def save_logs():
    """
    Speichert alle Logs als JSON & CSV.
    """
    json_filepath = "logs/review_process.json"
    csv_filepath = "logs/review_process.csv"

    with open(json_filepath, "w", encoding="utf-8") as file:
        json.dump(LOG_ENTRIES, file, indent=4)

    with open(csv_filepath, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["timestamp", "step", "message", "count"])
        writer.writeheader()
        writer.writerows(LOG_ENTRIES)

    print(f"✅ Logs gespeichert: {json_filepath}, {csv_filepath}")
