"""
===========================================================
PRISMA Workflow - System zur Automatisierung von Literatur-Reviews
===========================================================

Dieses Modul enthält die Hauptklasse `PRISMAWorkflow`, die den systematischen 
Literatur-Review-Prozess gemäß PRISMA steuert. Es umfasst:

1️⃣ Import von Literaturquellen (RIS/BibTeX)  
2️⃣ Duplikaterkennung und -entfernung  
3️⃣ Titel- und Abstract-Screening mit LLM  
4️⃣ Volltext-Screening mit LLM  
5️⃣ Export von verarbeiteten Daten  

Erweiterungen wie Data Extraction und Meta-Analysen sind später möglich.

Author: Dominique Truninger 
Version: 1.0  
"""
import pandas as pd
import uuid
from datetime import datetime
from enum import Enum
from literature_database import LiteratureDatabase
from literature_record import LiteratureRecord



class PRISMAState(Enum):
    """
    Enum für den aktuellen Zustand des PRISMA-Prozesses.
    Dies stellt sicher, dass die Pipeline in der richtigen Reihenfolge ausgeführt wird.
    """
    INITIAL = "Initial"
    IMPORTED = "Imported Literature Databases"
    DEDUPLICATED_SOURCES = "Deduplicated Individual Databases"
    MERGED = "Merged Databases"
    DEDUPLICATED_MERGED = "Deduplicated Merged Database"
    TITLE_ABSTRACT_SCREENED = "Title/Abstract Screening Completed"
    FULLTEXT_SCREENED = "Fulltext Screening Completed"
    REVIEW_COMPLETED = "Review Completed"



class PRISMAWorkflow:
    """
    Die Hauptklasse zur Steuerung des PRISMA-Prozesses.

    Funktionen:
    - Importiert Literaturquellen
    - Entfernt Duplikate
    - Führt Title/Abstract-Screening durch (mit LLM)
    - Führt Fulltext-Screening durch (mit LLM)
    - Exportiert die Ergebnisse als CSV
    
    Erweiterbar für zukünftige Prozesse wie Data Extraction.
    """

    def __init__(self):
        """
        Initialisiert den PRISMA-Prozess mit einem leeren Workflow.
        """
        self.sources = []  # Liste der importierten Literatur-Datenbanken
        self.merged_database = None  # Gesamtdatenbank nach Zusammenführung
        self.log_entries = []  # Liste der Prozess-Logs
        self.state = PRISMAState.INITIAL  # Startzustand

    def log(self, step, message):
        """
        Protokolliert einen Schritt des Prozesses mit Zeitstempel.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_entries.append(f"[{timestamp}] {step}: {message}")

    def import_sources(self, literature_databases):
        """
        Importiert eine Liste von Literatur-Datenbanken (RIS/BibTeX-Dateien).

        :param literature_databases: Liste von LiteratureDatabase-Objekten
        """
        self.sources.extend(literature_databases)
        self.state = PRISMAState.IMPORTED
        self.log("Import", f"Imported {len(literature_databases)} literature databases.")

    def remove_duplicates(self):
        """
        Entfernt doppelte Studien aus jeder einzelnen Literaturquelle.
        """
        for dataset in self.sources:
            before = len(dataset.records)
            dataset.records = list({(r.title, r.authors, r.year): r for r in dataset.records}.values())
            after = len(dataset.records)
            self.log("Deduplication", f"Removed {before - after} duplicates from {dataset.source_name}.")
        self.state = PRISMAState.DEDUPLICATED_SOURCES

    def merge_sources(self):
        """
        Führt alle importierten Literaturquellen zu einem einzigen Datensatz zusammen.
        """
        all_records = [record for source in self.sources for record in source.records]
        self.merged_database = LiteratureDatabase("MergedDatabase")
        self.merged_database.records = all_records
        self.state = PRISMAState.MERGED
        self.log("Merge", "Merged all sources into one dataset.")

    def remove_duplicates_merged(self):
        """
        Entfernt doppelte Studien aus der zusammengeführten Datenbank.
        """
        before = len(self.merged_database.records)
        self.merged_database.records = list({(r.title, r.authors, r.year): r for r in self.merged_database.records}.values())
        after = len(self.merged_database.records)
        self.state = PRISMAState.DEDUPLICATED_MERGED
        self.log("Deduplication", f"Removed {before - after} duplicates from merged dataset.")

    def title_abstract_screening(self, llm_model, research_question, inclusion_criteria, exclusion_criteria):
        """
        Führt das Titel- und Abstract-Screening durch ein LLM-Modell durch.

        :param llm_model: KI-Modell zur Analyse der Studien
        :param research_question: Forschungsfrage
        :param inclusion_criteria: Einschlusskriterien
        :param exclusion_criteria: Ausschlusskriterien
        """
        for record in self.merged_database.records:
            response = llm_model.analyze_text(record.title, record.abstract, research_question, inclusion_criteria, exclusion_criteria)
            record.set_screening_status("title_abstract_screening", response["decision"], response.get("reason"))

        self.state = PRISMAState.TITLE_ABSTRACT_SCREENED
        self.log("Screening", "Title/Abstract screening completed.")

    def fulltext_screening(self, llm_model):
        """
        Führt das Fulltext-Screening durch ein LLM-Modell durch.

        :param llm_model: KI-Modell zur Analyse des Volltexts
        """
        for record in self.merged_database.records:
            if record.title_abstract_screening == "included":
                response = llm_model.analyze_text(record.full_text)
                record.set_screening_status("full_text_screening", response["decision"], response.get("reason"))

        self.state = PRISMAState.FULLTEXT_SCREENED
        self.log("Screening", "Fulltext screening completed.")

    def export_results(self, filepath):
        """
        Speichert die Ergebnisse als CSV.

        :param filepath: Dateipfad für den Export
        """
        df = self.merged_database.to_dataframe()
        df.to_csv(filepath, index=False)
        self.state = PRISMAState.REVIEW_COMPLETED
        self.log("Export", f"Results exported to {filepath}.")
