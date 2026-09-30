# core/file_handler.py
# -*- coding: utf-8 -*-
"""
Robust bibliographic converter:
- Parse .ris (RIS), .bib (BibTeX) and .nbib (PubMed/MEDLINE) into pandas DataFrames
- Handle common encoding issues (utf-8/utf-8-sig, replace invalid chars)
- Heuristically detect wrong exports (e.g., MEDLINE content saved as .ris)
- Normalize core fields when possible: title, abstract, authors, year, journal, doi

Design goals:
- Keep existing public API stable (constructor signature, to_dataframe()).
- Do no network calls; only local parsing.
- Fail soft with clear error messages suitable for UI (Streamlit warnings allowed).
"""

from __future__ import annotations

from numpy import str_  # retained for backwards-compat
import os
import re
from typing import List, Dict, Any, Optional

import pandas as pd
import streamlit as st
import rispy
from pybtex.database.input import bibtex as pybib
from bibReader.frame import bReader
import tempfile


class BibliographicConverter:
    """
    Converts bibliographic data between RIS/BIB/NBIB files and pandas DataFrames.

    Usage:
        conv = BibliographicConverter(path, file_type="ris")  # file_type is a hint; content is sniffed
        df = conv.to_dataframe()
    """

    # RIS tag list (first two characters of each line).
    RIS_TAGS: List[str] = [
        'TY', 'A1', 'A2', 'A3', 'A4', 'AB', 'AD', 'AN', 'AU', 'AV', 'BT',
        'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8', 'CA', 'CN', 'CY',
        'DA', 'DB', 'DO', 'DP', 'ET', 'ID', 'IS', 'J2', 'JA', 'JF', 'JO',
        'KW', 'L1', 'L4', 'LA', 'LB', 'M1', 'M2', 'M3', 'N1', 'N2', 'NV',
        'OP', 'PB', 'PY', 'RI', 'RN', 'RP', 'SE', 'SN', 'SP', 'ST', 'T1',
        'T2', 'T3', 'TI', 'U1', 'U2', 'U3', 'U4', 'U5', 'UR', 'VL', 'Y1',
        'ER'
    ]

    # Default BibTeX fields if missing
    BIB_DEFAULT: Dict[str, Any] = {
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

    # Supported by extension; *content sniffing* can override this.
    SUPPORTED_TYPES = {'ris', 'bib', 'nbib'}

    def __init__(self, file_path: str, file_type: Optional[str] = None):
        """
        Parameters
        ----------
        file_path : str
            Path to the file on disk.
        file_type : Optional[str]
            Optional hint ("ris", "bib", "nbib"). If omitted or wrong, we sniff from
            extension and content. The hint is not authoritative.
        """
        self.file_path = file_path
        self.file_type_hint = (file_type or "").strip().lower() if file_type else None
        self.file_type = self._detect_file_type(file_path, self.file_type_hint)

    # ──────────────────────────────────────────────────────────────────────────
    # File type detection (extension + content sniffing)
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _detect_file_type(file_path: str, hint: Optional[str] = None) -> str:
        """
        Heuristically detect the file type:
        1) Start with hint if valid.
        2) Use extension.
        3) Sniff content (first ~4000 chars) to disambiguate RIS vs NBIB.

        Returns a best-effort type in {"ris","bib","nbib"}; raises if none match.
        """
        ext = (os.path.splitext(file_path)[1].lower().lstrip('.') or '').strip()
        # Normalize common variants
        ext = 'nbib' if ext in {'nbib', 'medline'} else ext

        # 1) if hint looks valid, start there
        if hint in BibliographicConverter.SUPPORTED_TYPES:
            guess = hint
        # 2) else use extension if looks valid
        elif ext in BibliographicConverter.SUPPORTED_TYPES:
            guess = ext
        else:
            guess = ''  # undecided

        # 3) content sniffing (only for ris/nbib confusion)
        try:
            head = BibliographicConverter._read_text(file_path, max_chars=4000)
        except Exception:
            head = ""

        # NBIB/MEDLINE heuristics: presence of "PMID-" and lines like "TI  -", "AB  -"
        looks_nbib = (
            'PMID-' in head or
            re.search(r'^\s*(TI|AB|JT|DP|FAU|AU)\s{2}-\s', head, flags=re.MULTILINE) is not None
        )
        # RIS heuristics: presence of TY  - and ER  - delimiters
        looks_ris = (
            re.search(r'^\s*TY\s{2}-\s', head, flags=re.MULTILINE) is not None and
            re.search(r'^\s*ER\s{2}-\s', head, flags=re.MULTILINE) is not None
        )

        if looks_nbib and not looks_ris:
            return 'nbib'
        if looks_ris and not looks_nbib:
            return 'ris'
        if guess:
            return guess

        # Last resort: try to parse as RIS; if that fails and we see PMID, call it NBIB.
        if 'PMID-' in head:
            return 'nbib'

        if ext in {'bib'}:
            return 'bib'

        # Nothing matched
        raise ValueError(f"Unsupported or undetected file type for: {file_path}")

    # ──────────────────────────────────────────────────────────────────────────
    # Robust text reading (UTF-8/UTF-8-SIG with tolerant fallback)
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _read_text(path: str, max_chars: Optional[int] = None) -> str:
        """
        Read file as UTF-8/UTF-8-SIG with replacement for bad bytes.
        Optional: truncate to max_chars to speed up sniffing.
        """
        try_encodings = ["utf-8-sig", "utf-8"]
        for enc in try_encodings:
            try:
                with open(path, "r", encoding=enc, errors="replace") as f:
                    data = f.read()
                return data[:max_chars] if (max_chars and len(data) > max_chars) else data
            except Exception:
                continue
        # very last fallback
        with open(path, "r", encoding="latin-1", errors="replace") as f:
            data = f.read()
        return data[:max_chars] if (max_chars and len(data) > max_chars) else data

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────
    def to_dataframe(self) -> pd.DataFrame:
        """Convert parsed entries to a DataFrame (normalized where possible)."""
        df = self.parse_file()
        return self._normalize(df, self.file_type)

    def parse_file(self) -> pd.DataFrame:
        """Parse the file and return a raw DataFrame (not yet normalized)."""
        if self.file_type == 'ris':
            return self._parse_ris()
        elif self.file_type == 'bib':
            # Prefer pybtex first (pure-parse, no side effects)
            try:
                result = self._parse_bib_pybtex(self.file_path)
                if not result.empty:
                    return result
            except Exception:
                pass
            # Then try bibReader (sandboxed to avoid writing side-effect files in CWD)
            try:
                result = self._parse_bib_bibreader(self.file_path)
                if not result.empty:
                    return result
            except Exception:
                pass
            # Use fallback parser as last resort
            st.info("Using fallback parser due to BibTeX parsing issues...")
            return self._parse_bib_fallback(self.file_path)
        elif self.file_type == 'nbib':
            return self._parse_nbib()
        else:
            raise ValueError(f"Unsupported file type: {self.file_type}")

    # ──────────────────────────────────────────────────────────────────────────
    # RIS parsing (robust encoding + tolerant tag filter)
    # ──────────────────────────────────────────────────────────────────────────
    def _parse_ris(self) -> pd.DataFrame:
        """Parse .ris files using rispy with explicit encoding handling."""
        try:
            text = self._read_text(self.file_path)
            # Filter lines to known tags; keep their original form
            lines = text.splitlines(True)
            filtered = [ln for ln in lines if ln[:2].strip() in self.RIS_TAGS]
            if not filtered:
                # maybe wrong format / MEDLINE saved as .ris
                if 'PMID-' in text:
                    raise Exception("This looks like PubMed/MEDLINE (NBIB), not RIS.")
                raise Exception("No recognizable RIS tags found.")
            entries = rispy.loads(''.join(filtered))
            return pd.DataFrame(entries)
        except FileNotFoundError:
            raise FileNotFoundError(f"The file {self.file_path} was not found.")
        except Exception as e:
            raise Exception(f"RIS parsing failed: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # NBIB (PubMed/MEDLINE) parsing
    # ──────────────────────────────────────────────────────────────────────────
    def _parse_nbib(self) -> pd.DataFrame:
        """
        Parse .nbib (PubMed/MEDLINE) into a DataFrame.
        Records are typically separated by a blank line; fields use keys like:
          PMID-, TI  -, AB  -, JT  -, DP  -, FAU -, AU  -, AID -, OT  -, MH  -, LID -
        We'll map the most common ones to standard columns.
        """
        text = self._read_text(self.file_path)
        # Normalize line endings and ensure trailing newline
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        if not text.endswith('\n'):
            text += '\n'

        # Split into records by blank lines with a "PMID-" anchor
        # More robust: split whenever a new PMID- starts
        raw_records: List[str] = re.split(r'\n(?=PMID-\s*\d+)', text.strip(), flags=re.MULTILINE)
        records: List[Dict[str, Any]] = []

        for block in raw_records:
            if not block.strip():
                continue
            rec = self._parse_nbib_block(block)
            if rec:
                records.append(rec)

        return pd.DataFrame(records)

    def _parse_nbib_block(self, block: str) -> Optional[Dict[str, Any]]:
        """
        Parse one NBIB/MEDLINE block into a dictionary.
        """
        lines = block.splitlines()
        data: Dict[str, Any] = {}
        # Accumulate multi-line fields: continue lines begin with 6 spaces in MEDLINE (.nbib)
        current_key = None
        current_val = []

        def commit_current():
            nonlocal current_key, current_val
            if current_key is None:
                return
            val = ' '.join(v.strip() for v in current_val if v is not None)
            # Append or set
            if current_key in data:
                # existing list
                if isinstance(data[current_key], list):
                    data[current_key].append(val)
                else:
                    data[current_key] = [data[current_key], val]
            else:
                data[current_key] = val
            current_key, current_val = None, []

        for ln in lines:
            # Continuation line? MEDLINE uses 6-space indents for wrapped text.
            if re.match(r'^\s{6,}\S', ln):
                current_val.append(ln.strip())
                continue

            # New key line: e.g. "TI  - Title text"
            m = re.match(r'^\s*([A-Z0-9]{2,4})\s{2}-\s(.*)$', ln)
            if m:
                # Commit previous key
                commit_current()
                current_key = m.group(1)
                current_val = [m.group(2)]
            else:
                # tolerate noise: commit previous if a blank line found
                if ln.strip() == "":
                    commit_current()
                else:
                    # Unexpected line; push as continuation
                    if current_key is not None:
                        current_val.append(ln.strip())

        # Commit last key
        commit_current()

        if not data:
            return None

        # Map NBIB fields to normalized keys
        mapped: Dict[str, Any] = {}

        # PMID
        pmid = _first_or_none(data.get("PMID"))
        if pmid:
            mapped["pmid"] = pmid

        # Title (TI  -)
        title = _first_or_none(data.get("TI"))
        if not title:
            # Alternative: Article Title (TI is standard; sometimes "TT" is Translated Title)
            title = _first_or_none(data.get("TT"))
        if title:
            mapped["title"] = title

        # Abstract (AB  -)
        abstract = _first_or_none(data.get("AB"))
        if abstract:
            mapped["abstract"] = abstract

        # Journal title (JT  -)
        journal = _first_or_none(data.get("JT"))
        if journal:
            mapped["journal"] = journal

        # Publication Date (DP  -) → year
        dp = _first_or_none(data.get("DP"))
        if dp:
            yr = _extract_year(dp)
            if yr:
                mapped["year"] = yr

        # Authors: prefer FAU (Full Author) list; else AU
        authors_list = _ensure_list(data.get("FAU")) or _ensure_list(data.get("AU"))
        if authors_list:
            mapped["authors"] = "; ".join(authors_list)

        # DOI can appear in AID "10.xxxx [doi]" or LID lines
        doi = _extract_doi_from_aid(_ensure_list(data.get("AID"))) or _extract_doi_from_lid(_ensure_list(data.get("LID")))
        if doi:
            mapped["doi"] = doi

        # Keywords: OT (Other Terms) or MeSH MH
        kws = _ensure_list(data.get("OT")) or _ensure_list(data.get("MH"))
        if kws:
            mapped["keywords"] = "; ".join(kws)

        # URL: If DOI present, create doi.org URL
        if "doi" in mapped:
            mapped["url"] = f"https://doi.org/{mapped['doi']}"

        # Fallback: if still empty title+abstract, consider record invalid
        if not mapped.get("title") and not mapped.get("abstract"):
            # keep minimal record but mark it
            mapped["raw_block"] = block

        return mapped

    # ──────────────────────────────────────────────────────────────────────────
    # BibTeX parsing (three strategies)
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def _parse_bib_bibreader(cls, path: str) -> pd.DataFrame:
        """Parse .bib files using bibReader."""
        try:
            # Sandbox execution in a temporary directory to avoid polluting the project root.
            cwd = os.getcwd()
            with tempfile.TemporaryDirectory() as tmpdir:
                try:
                    os.chdir(tmpdir)
                    br = bReader()
                    br.load(source=path)
                    br.fit()
                    br.transform()
                    df = br.df if hasattr(br, 'df') and br.df is not None else pd.DataFrame()
                finally:
                    os.chdir(cwd)
            return df
        except Exception as e:
            st.warning(f"Failed to parse BibTeX file with bibReader: {str(e)}")
            return pd.DataFrame()

    @classmethod
    def _parse_bib_pybtex(cls, path: str) -> pd.DataFrame:
        """Parse .bib files using pybtex."""
        try:
            parser = pybib.Parser()
            bibdata = parser.parse_file(path)
            records = []
            for key, entry in bibdata.entries.items():
                try:
                    rec = {k: cls.clean_latex(v) for k, v in entry.fields.items()}
                    rec['ID'] = key
                    rec['type'] = entry.type
                    authors = entry.persons.get('author', [])
                    rec['author'] = " and ".join(
                        cls.clean_latex(" ".join([p.first(), p.last()]).strip())
                        for p in authors
                    )
                    records.append(rec)
                except Exception as e:
                    st.warning(f"Failed to parse entry {key}: {str(e)}")
                    continue
            return pd.DataFrame(records)
        except Exception as e:
            st.error(f"Failed to parse BibTeX file with pybtex: {str(e)}")
            return pd.DataFrame()

    @classmethod
    def _parse_bib_fallback(cls, path: str) -> pd.DataFrame:
        """Fallback BibTeX parser for files with problematic LaTeX."""
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as file:
                content = file.read()
            entries = []
            entry_pattern = r'@(\w+)\{([^,]+),\s*((?:[^}]|{[^}]*})*)\}'
            matches = re.findall(entry_pattern, content, re.DOTALL)
            for entry_type, key, fields_text in matches:
                entry = {'ID': key.strip(), 'type': entry_type}
                field_pattern = r'(\w+)\s*=\s*{([^}]*(?:{[^}]*}[^}]*)*)}'
                field_matches = re.findall(field_pattern, fields_text)
                for field_name, field_value in field_matches:
                    cleaned_value = cls.clean_latex(field_value.strip())
                    entry[field_name.lower()] = cleaned_value
                entries.append(entry)
            return pd.DataFrame(entries)
        except Exception as e:
            st.error(f"Fallback BibTeX parsing also failed: {str(e)}")
            return pd.DataFrame()

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers: LaTeX cleanup, defaults, normalization
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def clean_latex(text: Any) -> str:
        """Clean LaTeX formatting from text (best-effort, safe)."""
        if not isinstance(text, str):
            return text or ''
        try:
            text = re.sub(r"\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^}]*\})?", "", text)
            text = re.sub(r"\\[a-zA-Z]+", "", text)
            # Handle braces
            brace_count = 0
            cleaned_chars = []
            for char in text:
                if char == '{':
                    brace_count += 1
                    if brace_count <= 1:
                        cleaned_chars.append(char)
                elif char == '}':
                    brace_count -= 1
                    if brace_count >= 0:
                        cleaned_chars.append(char)
                else:
                    cleaned_chars.append(char)
            text = ''.join(cleaned_chars)
            text = re.sub(r"[{}\\]", "", text)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()
        except Exception:
            try:
                text = re.sub(r"\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^}]*\})?", "", text)
                text = re.sub(r"[{}\\]", "", text)
                text = re.sub(r'\s+', ' ', text)
                return text.strip()
            except Exception:
                return re.sub(r'[{\\}\\]', '', str(text)).strip()

    @classmethod
    def ensure_bibtex_fields(cls, entry: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Ensure a BibTeX entry has all required fields."""
        for key, default_value in cls.BIB_DEFAULT.items():
            if key not in entry:
                entry[key] = default_value if key != 'ID' else f"{default_value}{index}"
            if key == 'keywords' and not isinstance(entry[key], str):
                entry[key] = ', '.join(entry[key]) if isinstance(entry[key], list) else str(entry[key])
        return entry

    @staticmethod
    def _normalize(df: pd.DataFrame, kind: str) -> pd.DataFrame:
        """
        Normalize core fields to consistent column names where possible:
          - title
          - abstract
          - authors (string "A; B; C")
          - year (int-like)
          - journal
          - doi
        This is best-effort and won't drop original fields.
        """
        if df is None or df.empty:
            return pd.DataFrame()

        out = df.copy()

        # RIS via rispy usually provides 'title', 'abstract', 'authors', 'year', 'journal_name', 'doi'
        # NBIB parser maps directly to our normalized keys.
        # BibTeX may use 'author' (single string) and 'year' as string.

        # title
        if 'title' not in out.columns:
            for cand in ['TI', 't1', 'primary_title']:
                if cand in out.columns:
                    out['title'] = out[cand]
                    break

        # abstract
        if 'abstract' not in out.columns:
            for cand in ['AB', 'N2', 'abstract_note']:
                if cand in out.columns:
                    out['abstract'] = out[cand]
                    break

        # authors
        if 'authors' not in out.columns:
            if 'author' in out.columns:
                out['authors'] = out['author']
            elif 'AU' in out.columns:
                out['authors'] = out['AU']
        # Ensure authors become string (e.g., list from rispy)
        if 'authors' in out.columns:
            out['authors'] = out['authors'].apply(_authors_to_string)

        # year
        if 'year' not in out.columns:
            for cand in ['PY', 'Y1', 'date', 'year_pub']:
                if cand in out.columns:
                    out['year'] = out[cand]
                    break
        # Try to coerce to int-like year
        if 'year' in out.columns:
            out['year'] = out['year'].apply(_coerce_year)

        # journal
        if 'journal' not in out.columns:
            for cand in ['journal_name', 'JO', 'JF', 'JA', 'JT']:
                if cand in out.columns:
                    out['journal'] = out[cand]
                    break

        # doi
        if 'doi' not in out.columns:
            for cand in ['DO', 'lid', 'AID']:
                if cand in out.columns:
                    out['doi'] = out[cand]
                    break

        return out

    # ──────────────────────────────────────────────────────────────────────────
    # Utilities (batch)
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def batch_to_dataframes(uploaded_files: List) -> pd.DataFrame:
        """
        Process multiple uploaded files and return a combined DataFrame.
        NOTE: This helper writes each UploadedFile to disk temporarily,
        parses it, and concatenates results. It now accepts MIXED types.
        """
        if not uploaded_files:
            return pd.DataFrame()

        data_df = pd.DataFrame()
        successful_files = 0
        failed_files = 0

        for file in uploaded_files:
            try:
                file_ext = os.path.splitext(file.name)[1].lower()
                hint = file_ext.lstrip(".")
                tmp_path = file.name  # local temp name in CWD
                with open(tmp_path, "wb") as f:
                    f.write(file.getbuffer())

                conv = BibliographicConverter(tmp_path, file_type=hint)
                df = conv.to_dataframe()

                if not df.empty:
                    data_df = pd.concat([data_df, df], ignore_index=True)
                    successful_files += 1
                else:
                    st.warning(f"File {file.name} was parsed but returned no entries.")
                    failed_files += 1

            except Exception as e:
                st.error(f"Failed to parse file {file.name}: {str(e)}")
                failed_files += 1
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        if successful_files > 0:
            st.success(f"Successfully processed {successful_files} file(s) with {len(data_df)} total entries.")
        if failed_files > 0:
            st.warning(f"Failed to process {failed_files} file(s).")

        return data_df


# ──────────────────────────────────────────────────────────────────────────────
# Small helpers (module scope)
# ──────────────────────────────────────────────────────────────────────────────

def _first_or_none(x: Any) -> Optional[str]:
    if x is None:
        return None
    if isinstance(x, list):
        return str(x[0]) if x else None
    return str(x)


def _ensure_list(x: Any) -> Optional[List[str]]:
    if x is None:
        return None
    if isinstance(x, list):
        return [str(i) for i in x]
    return [str(x)]


def _extract_year(s: str) -> Optional[int]:
    if not s:
        return None
    m = re.search(r'(\d{4})', s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def _authors_to_string(val: Any) -> str:
    """
    Normalize authors to a single string "A; B; C".
    - rispy may give list of dicts or list of strings.
    - BibTeX often has "A and B and C" in 'author'.
    """
    if val is None:
        return ""
    if isinstance(val, list):
        # list of dicts from rispy? e.g., [{'given':..., 'family':...}]
        if val and isinstance(val[0], dict):
            parts = []
            for a in val:
                given = (a.get('given') or '').strip()
                family = (a.get('family') or '').strip()
                name = " ".join(p for p in [given, family] if p)
                if not name:
                    name = (a.get('name') or '').strip()
                if name:
                    parts.append(name)
            return "; ".join(parts)
        else:
            return "; ".join([str(x) for x in val])
    # string (maybe "A and B and C")
    s = str(val)
    if " and " in s and ";" not in s:
        parts = [p.strip() for p in s.split(" and ") if p.strip()]
        return "; ".join(parts)
    return s


def _extract_doi_from_aid(aid_lines: Optional[List[str]]) -> Optional[str]:
    """
    AID lines can look like: '10.1000/j.jmb.2010.08.031 [doi]'
    Return the first DOI-ish token.
    """
    if not aid_lines:
        return None
    doi_pat = re.compile(r'\b10\.\d{4,9}/\S+\b', re.IGNORECASE)
    for ln in aid_lines:
        m = doi_pat.search(ln)
        if m:
            return m.group(0).rstrip('.,; ')
    return None


def _extract_doi_from_lid(lid_lines: Optional[List[str]]) -> Optional[str]:
    """
    LID lines may also include DOI. We try the same pattern.
    """
    if not lid_lines:
        return None
    doi_pat = re.compile(r'\b10\.\d{4,9}/\S+\b', re.IGNORECASE)
    for ln in lid_lines:
        m = doi_pat.search(ln)
        if m:
            return m.group(0).rstrip('.,; ')
    return None


def _coerce_year(v: Any) -> Any:
    """
    Try to coerce common year shapes to an int-like year; fallback to original.
    """
    if v is None:
        return None
    s = str(v)
    m = re.search(r'(\d{4})', s)
    if not m:
        return v
    try:
        return int(m.group(1))
    except Exception:
        return v
