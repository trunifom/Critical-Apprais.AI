import pandas as pd
from datetime import datetime

class LiteratureSearchDataset:
    """
    Represents a dataset from a single literature search.
    Stores metadata such as database label, timestamp, and duplicate statistics.
    """

    def __init__(self, label, dataframe):
        """
        Initializes a LiteratureSearchDataset.
        
        :param label: Name of the dataset (e.g., database name).
        :param dataframe: Pandas DataFrame containing bibliographic data.
        """
        self._label = label
        self._dataframe = dataframe
        self._original_size = len(dataframe)  # Store original size
        self._duplicates_found = 0
        self._duplicates_removed = 0
        self._final_count = self._original_size  # Neu hinzugefügt
        self._log = []
        
        self._log_action(f"Dataset '{self._label}' created with {self._original_size} entries.")

    def _log_action(self, action: str):
        """Records an action in the dataset's log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._log.append(f"[{timestamp}] {action}")

    def find_duplicates(self, subset=None):
        """
        Identifies duplicate entries in the dataset.

        :param subset: Columns to consider for duplicate detection.
        :return: DataFrame of detected duplicates.
        """
        if subset is None:
            subset = ["title", "authors", "year"]  # Falsche Spalten korrigiert

        # Ensure that all subset columns exist in the DataFrame
        missing_columns = [col for col in subset if col not in self._dataframe.columns]
        if missing_columns:
            raise KeyError(f"ERROR: Columns {missing_columns} do not exist in DataFrame!")

        # Convert 'authors' column to a hashable type
        self._dataframe["authors"] = self._dataframe["authors"].apply(lambda x: str(x) if isinstance(x, list) else x)

        duplicates = self._dataframe.duplicated(subset=subset, keep=False)
        self._duplicates_found = duplicates.sum()
        self._log_action(f"Found {self._duplicates_found} duplicate entries.")
        return self._dataframe[duplicates]

    def remove_duplicates(self, subset=None):
        """
        Removes duplicate entries from the dataset.
        
        :param subset: Columns to consider for duplicate detection.
        """
        if subset is None:
            subset = ["title", "authors", "year"]  # Falsche Spalten korrigiert

        missing_columns = [col for col in subset if col not in self._dataframe.columns]
        if missing_columns:
            raise KeyError(f"ERROR: Columns {missing_columns} do not exist in DataFrame!")

        # Convert 'authors' column to a hashable type
        self._dataframe["authors"] = self._dataframe["authors"].apply(lambda x: str(x) if isinstance(x, list) else x)

        initial_count = len(self._dataframe)
        self._dataframe = self._dataframe.drop_duplicates(subset=subset, keep='first')
        self._duplicates_removed = initial_count - len(self._dataframe)
        self._final_count = len(self._dataframe)
        self._log_action(f"Removed {self._duplicates_removed} duplicate entries.")


    def get_log(self):
        """Returns the log of actions performed on this dataset."""
        return "\n".join(self._log)

    # Getter-Methoden
    def get_label(self):
        """Returns the label of the dataset."""
        return self._label

    def get_original_count(self):
        return self._original_size  # Neu hinzugefügt

    def get_duplicates_found(self):
        return self._duplicates_found

    def get_duplicates_removed(self):
        return self._duplicates_removed

    def get_final_count(self):
        return self._final_count  # Neu hinzugefügt

    def get_dataframe(self):
        """Returns the DataFrame of the dataset."""
        return self._dataframe


class LiteratureReviewDataset:
    """
    Represents a combined dataset from multiple literature searches.
    Allows merging multiple LiteratureSearchDataset instances into a single dataset.
    """

    def __init__(self, label: str, datasets=None):
        """
        Initializes a literature review dataset.

        :param label: The label identifying the combined dataset.
        :param datasets: Optional list of LiteratureSearchDataset instances to merge.
        """
        self._label = label
        self._datasets = []
        self._dataframe = pd.DataFrame()
        self._merged_labels = []
        self._original_count = 0
        self._duplicates_found = 0
        self._duplicates_removed = 0
        self._final_count = 0
        self._log = []

        self._log_action(f"Literature review dataset '{label}' created.")

        # Falls beim Erstellen bereits Datensätze übergeben wurden, sofort mergen
        if datasets:
            self.merge_datasets(datasets)

    def _log_action(self, action: str):
        """Records an action in the dataset's log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._log.append(f"[{timestamp}] {action}")

    def merge_datasets(self, datasets):
        """
        Merges multiple LiteratureSearchDataset instances into the LiteratureReviewDataset.

        :param datasets: List of LiteratureSearchDataset instances to merge.
        """
        for dataset in datasets:
            if not isinstance(dataset, LiteratureSearchDataset):
                raise TypeError(f"Invalid dataset type: {type(dataset)}. Expected LiteratureSearchDataset.")

            self._datasets.append(dataset)
            self._merged_labels.append(dataset.get_label())
            self._original_count += dataset.get_original_count()  # Fix für get_original_count

        all_data = [dataset.get_dataframe() for dataset in self._datasets if not dataset.get_dataframe().empty]
        if all_data:
            self._dataframe = pd.concat(all_data, ignore_index=True)
            self._log_action(f"Merged {len(datasets)} datasets into literature review dataset '{self._label}'.")
        else:
            self._log_action(f"No valid datasets to merge into '{self._label}'.")


    def find_duplicates(self, subset=None):
        """Finds duplicates in the merged dataset."""
        duplicates = self._dataframe.duplicated(subset=subset, keep=False)
        self._duplicates_found = duplicates.sum()
        self._log_action(f"Found {self._duplicates_found} duplicate entries.")
        return self._dataframe[duplicates]

    def remove_duplicates(self, subset=None):
        """Removes duplicates from the merged dataset."""
        initial_count = len(self._dataframe)
        self._dataframe = self._dataframe.drop_duplicates(subset=subset, keep='first')
        self._duplicates_removed = initial_count - len(self._dataframe)
        self._final_count = len(self._dataframe)
        self._log_action(f"Removed {self._duplicates_removed} duplicate entries.")

    def get_log(self):
        """Returns the log of actions performed on this dataset."""
        return "\n".join(self._log)

    # Getter-Methoden
    def get_label(self):
        return self._label

    def get_merged_labels(self):
        return self._merged_labels

    def get_original_count(self):
        return self._original_count  # Fix für `get_original_count`

    def get_duplicates_found(self):
        return self._duplicates_found

    def get_duplicates_removed(self):
        return self._duplicates_removed

    def get_final_count(self):
        return self._final_count

    def get_dataframe(self):
        return self._dataframe


