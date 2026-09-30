import os
import unittest
import pandas as pd
from glob import glob
#from tools.literaturdataset import LiteratureSearchDataset, LiteratureReviewDataset
#from tools.processing import BibliographicConverter  # Zum Laden der RIS-Dateien

import sys
# Projektverzeichnis zum Python-Pfad hinzufügen
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from tools.literaturdataset import LiteratureSearchDataset, LiteratureReviewDataset
from tools.processing import BibliographicConverter  # Zum Laden der RIS-Dateien

class TestLiteratureSearchDataset(unittest.TestCase):
    """Unit tests for LiteratureSearchDataset class."""

    @classmethod
    def setUpClass(cls):
        """Load RIS files from the test_data directory and convert them to LiteratureSearchDataset instances."""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        cls.test_data_dir = os.path.join(project_root, "tests", "test_data", "example_ris")
        cls.ris_files = glob(os.path.join(cls.test_data_dir, "*.ris"))
        cls.datasets = []

        for ris_file in cls.ris_files:
            label = os.path.basename(ris_file).replace(".ris", "")  # Entfernt die Endung ".ris"
            converter = BibliographicConverter(ris_file)
            dataframe = converter.to_dataframe()

            dataset = LiteratureSearchDataset(label=label, dataframe=dataframe)
            cls.datasets.append(dataset)

    def test_initialization(self):
        """Test if LiteratureSearchDataset initializes correctly."""
        for dataset in self.datasets:
            self.assertIsInstance(dataset, LiteratureSearchDataset)
            self.assertIsInstance(dataset.get_dataframe(), pd.DataFrame)
            self.assertGreater(dataset.get_original_count(), 0)  # Der ursprüngliche Count sollte > 0 sein
            self.assertIsNotNone(dataset.get_label())  # Das Label sollte existieren

    def test_find_duplicates(self):
        """Test duplicate detection in datasets."""
        expected_duplicates = {
            "example_db_nr1_total-15_duplicates-0": 0,
            "example_db_nr2_total-10_duplicates-3": 3,
            "example_db_nr3_total-8_duplicates-2": 2,
        }

        for dataset in self.datasets:
            duplicates = dataset.find_duplicates(subset = ["title", "authors", "year"])
            self.assertEqual(dataset.get_duplicates_found(), expected_duplicates[dataset.get_label()])

    def test_remove_duplicates(self):
        """Test duplicate removal in datasets."""
        expected_remaining_entries = {
            "example_db_nr1_total-15_duplicates-0": 15,
            "example_db_nr2_total-10_duplicates-3": 7,  # 10 - 3 Duplikate
            "example_db_nr3_total-8_duplicates-2": 6,   # 8 - 2 Duplikate
        }

        for dataset in self.datasets:
            dataset.remove_duplicates(subset = ["title", "authors", "year"])
            self.assertEqual(dataset.get_final_count(), expected_remaining_entries[dataset.get_label()])

class TestLiteratureReviewDataset(unittest.TestCase):
    """Unit tests for LiteratureReviewDataset class."""

    @classmethod
    def setUpClass(cls):
        """Setup review dataset with merged literature search datasets."""
        if not hasattr(TestLiteratureSearchDataset, "datasets"):
            TestLiteratureSearchDataset.setUpClass()

        cls.review_dataset = LiteratureReviewDataset(label="Merged Review", datasets=TestLiteratureSearchDataset.datasets)

    def test_merge_datasets(self):
        """Test merging multiple LiteratureSearchDataset instances into LiteratureReviewDataset."""
        total_entries_before_dedup = sum(ds.get_original_count() for ds in TestLiteratureSearchDataset.datasets)
        self.assertEqual(self.review_dataset.get_original_count(), total_entries_before_dedup)

    def test_find_duplicates_after_merge(self):
        """Test duplicate detection in the merged dataset."""
        self.review_dataset.find_duplicates(subset = ["title", "authors", "year"])
        self.assertGreater(self.review_dataset.get_duplicates_found(), 0)

    def test_remove_duplicates_after_merge(self):
        """Test duplicate removal in the merged dataset."""
        initial_count = self.review_dataset.get_final_count()
        #self.review_dataset.remove_duplicates(subset=["TI", "AU", "PY"])
        self.review_dataset.remove_duplicates(subset = ["title", "authors", "year"])
        self.assertLess(self.review_dataset.get_final_count(), initial_count)

    def test_get_merged_labels(self):
        """Test if all dataset labels are stored correctly after merging."""
        expected_labels = [ds.get_label() for ds in TestLiteratureSearchDataset.datasets]
        self.assertEqual(self.review_dataset.get_merged_labels(), expected_labels)

if __name__ == "__main__":
    unittest.main()



