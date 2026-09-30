import rispy
import bibtexparser
import pandas as pd

class BibliographicConverter:
    """ 
    A class to convert bibliographic data from RIS/BIB files to DataFrames and vice versa. 

    Attributes:
    file_path (str): Path to the RIS/BIB file.
    file_type (str): Type of the file (RIS or BIB).

    Methods:
    filter_ris_lines(): Filters RIS file lines to only include those with valid RIS tags.
    parse_file(): Parses the RIS/BIB file and return a list of reference entries.
    ensure_bibtex_fields(entry, index): Ensures that a Bibtex entry has the required fields and correct types.
    to_dataframe(): Converts the parsed reference entries to a DataFrame.
    to_bib(df_bib, output_path): Converts a .bib based DataFrame to a Bibtex file.
    to_ris(df_ris, output_path): Converts a .ris based DataFrame to a RIS file.
    
    """

    RIS_TAGS = ['TY', 'A1', 'A2', 'A3', 'A4', 'AB', 'AD', 'AN', 'AU', 'AV', 'BT', 
                'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8', 'CA', 'CN', 'CY', 
                'DA', 'DB', 'DO', 'DP', 'ET', 'ID', 'IS', 'J2', 'JA', 'JF', 'JO', 
                'KW', 'L1', 'L4', 'LA', 'LB', 'M1', 'M2', 'M3', 'N1', 'N2', 'NV', 
                'OP', 'PB', 'PY', 'RI', 'RN', 'RP', 'SE', 'SN', 'SP', 'ST', 'T1', 
                'T2', 'T3', 'TI', 'U1', 'U2', 'U3', 'U4', 'U5', 'UR', 'VL', 'Y1', 
                'ER']
                
    
    BIB_DEFAULT = {
        'ENTRYTYPE': 'misc',
        'ID': 'entry',  # Generate a unique ID if ID is missing
        'author': 'Unknown',
        'title': 'Untitled',
        'year': '1900',
        'journal': 'Unknown Journal',
        'volume': '0',
        'number': '0',
        'pages': '0-0',
        'month': 'jan',
        'note': '',
        'doi': '',
        'keywords': '',
        'abstract': '',
        'url': '',
        }
    
    FILE_TYPE_RIS = 'ris'
    FILE_TYPE_BIB = 'bib'

    def __init__(self, file_path):
        self.file_path = file_path
        self.file_type = file_path.split('.')[-1]


    def filter_ris_lines(self):
        """ Filters RIS file lines to only include those with valid RIS tags. """
        try:
            with open(self.file_path, 'r', encoding="utf-8") as file:  # UTF-8
                filtered_lines = [line for line in file if line[:2] in self.RIS_TAGS]
            return filtered_lines
        except FileNotFoundError:
            print(f"Error: The file {self.file_path} was not found.")
            return []
        except Exception as e:
            print(f"An error occurred: {e}")
            return []


    def parse_file(self):
        """ Parses the RIS/BIB file and return a list of reference entries. """
        if self.file_type == self.FILE_TYPE_RIS:
            filtered_content = self.filter_ris_lines()
            ref_entries = rispy.loads(''.join(filtered_content))
        elif self.file_type == self.FILE_TYPE_BIB:
            try:
                with open(self.file_path, 'r') as bibliography_file:
                    bib = bibtexparser.load(bibliography_file)
                ref_entries = bib.entries
            except FileNotFoundError:
                print(f"Error: The file {self.file_path} was not found.")
                return []
            except Exception as e:
                print(f"An error occurred: {e}")
                return []
        else:
            print(f"Error: Unsupported file type {self.file_type}.")
            return []
        
        return ref_entries


    def ensure_bibtex_fields(self, entry, index):
        """ 
        Ensures that a Bibtex entry has the required fields and correct types. 
        Args:
            entry (dict): A dictionary representing a Bibtex entry.
            index (int): Index of the entry in the list of entries.

        Returns:
            dict: A dictionary representing a Bibtex entry with the required fields and correct types.
        """

        
        for key, default_value in self.BIB_DEFAULT.items():
            if key not in entry:
                entry[key] = default_value if key != 'ID' else f"{default_value}{index}"
            if key == 'keywords' and not isinstance(entry[key], str):
                entry[key] = ', '.join(entry[key]) if isinstance(entry[key], list) else str(entry[key])
        
        return entry
    

    def to_dataframe(self):
        """ Converts the parsed reference entries to a DataFrame. """
        entries = self.parse_file()
        print(f"DEBUG: Loaded {len(entries)} entries from {self.file_path}")  # Debug

        if entries:
            df_entries = pd.DataFrame(entries)
            print(f"DEBUG: DataFrame Columns: {df_entries.columns}")  # Debug
            return df_entries
        else:
            print(f"ERROR: No entries found in {self.file_path}. Check file encoding and content.")
            return pd.DataFrame()


    def to_bib(self, df_bib, output_path):
        """ 
        Converts a .bib based DataFrame to a Bibtex file. 
        Args:
            df (pd.DataFrame): DataFrame containing bibliographic data.
            output_path (str): Path to save the Bibtex file.
            
        Returns:
            None        
        """
        entries_dict = df_bib.to_dict(orient='records')
        entries = [self.ensure_bibtex_fields(entry, i) for i, entry in enumerate(entries_dict)]
        
        bib_database = bibtexparser.bibdatabase.BibDatabase()
        bib_database.entries = entries
        
        with open(output_path, 'w') as bibfile:
            bibtexparser.dump(bib_database, bibfile)


    def to_ris(self, df_ris, output_path):
        """
        Converts a .ris based DataFrame to a RIS file.
        Args:
            df (pd.DataFrame): DataFrame containing bibliographic data.
            output_path (str): Path to save the RIS file.
            
        Returns:
            None
        """
        entries = df_ris.to_dict(orient='records')
        with open(output_path, 'w') as risfile:
            rispy.dump(entries, risfile)




