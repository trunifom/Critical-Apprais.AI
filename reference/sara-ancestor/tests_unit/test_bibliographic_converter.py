import unittest
import pandas as pd
import os, sys
sys.path.insert(0, os.path.abspath("./"))  # insert the path at the first position

from tools.processing import BibliographicConverter

class TestBibliographicConverter(unittest.TestCase):

    def setUp(self):
        self.ris_file = 'tests/test_data/cochrane_db/citation-export.ris'
        self.bib_file = 'tests/test_data/cochrane_db/citation-export.bib'
        self.converter_ris = BibliographicConverter(self.ris_file)
        self.converter_bib = BibliographicConverter(self.bib_file)

    def test_initialization(self):
        self.assertEqual(self.converter_ris.file_type, 'ris')
        self.assertEqual(self.converter_bib.file_type, 'bib')

    def test_parse_ris_file(self):
        entries = self.converter_ris.parse_file()
        self.assertIsInstance(entries, list)
        self.assertGreater(len(entries), 0)

    def test_parse_bib_file(self):
        entries = self.converter_bib.parse_file()
        self.assertIsInstance(entries, list)
        self.assertGreater(len(entries), 0)

    def test_filter_ris_lines(self):
        filtered_lines = self.converter_ris.filter_ris_lines()
        self.assertIsInstance(filtered_lines, list)
        self.assertGreater(len(filtered_lines), 0)
        for line in filtered_lines:
            self.assertIn(line[:2], self.converter_ris.RIS_TAGS)

    def test_to_dataframe(self):
        df = self.converter_ris.to_dataframe()
        self.assertIsInstance(df, pd.DataFrame)
        self.assertGreater(len(df), 0)

    def test_to_bib(self):
        df = self.converter_bib.to_dataframe()
        output_path = 'tests/output/output.bib'
        self.converter_bib.to_bib(df, output_path)
        with open(output_path, 'r') as file:
            content = file.read()
        self.assertIn('abstract', content)
        self.assertIn('title', content)
        self.assertIn('doi', content)


    def test_to_ris(self):
        df = self.converter_ris.to_dataframe()
        output_path = 'tests/output/output.ris'
        self.converter_ris.to_ris(df, output_path)
        with open(output_path, 'r') as file:
            content = file.read()
        self.assertIn('DO', content)
        self.assertIn('AB', content)

if __name__ == '__main__':
    unittest.main()
