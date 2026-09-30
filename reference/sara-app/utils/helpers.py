import io
from typing import List
import bibtexparser
import rispy
import json
import streamlit as st

# Constants for prompt loading
PROMPTS_PATH                = st.secrets["prompt_params"]["prompts_path"]
PROMPT_TYPE_ABSTRACT        = st.secrets["prompt_params"]["prompt_type_abstract"]
PROMPT_TYPE_FULLTEXT        = st.secrets["prompt_params"]["prompt_type_fulltext"]


# ──────────────────────────────────────────────────────────────────────────────
# File parsing helpers
# ──────────────────────────────────────────────────────────────────────────────
def parse_bib_file(file):
    bib_database = bibtexparser.load(file)
    entries = bib_database.entries
    return entries

def parse_ris_file(file):
    entries = rispy.load(file)
    return entries


def extract_text_from_pdf_bytes(data: bytes) -> str:
    """Best-effort PDF text extraction from raw bytes using layered backends.

    Order: PyMuPDF (fitz) → pdfplumber. Returns empty string if both fail.
    """
    # Try PyMuPDF (fitz)
    try:
        import fitz  # type: ignore
        parts: List[str] = []
        with fitz.open(stream=data, filetype="pdf") as doc:  # type: ignore
            for page in doc:  # type: ignore
                try:
                    parts.append(page.get_text("text"))  # type: ignore[attr-defined]
                except Exception:
                    continue
        return "\n".join([t for t in parts if t])
    except Exception:
        pass

    # Try pdfplumber
    try:
        import pdfplumber  # type: ignore
        parts = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:  # type: ignore
            for page in pdf.pages:
                try:
                    t = page.extract_text() or ""
                    if t:
                        parts.append(t)
                except Exception:
                    continue
        return "\n".join([t for t in parts if t])
    except Exception:
        pass

    return ""

# ──────────────────────────────────────────────────────────────────────────────
# Data loading helpers
# ──────────────────────────────────────────────────────────────────────────────
def load_prompt_template(mode) -> str:
    """
    Load the prompt text used by the model (if available). We try to fetch PROMPT_TYPE
    from the JSON file (PROMPTS_PATH). If not found, return the whole JSON string
    or a simple fallback.
    """
    assert mode in ("abstract", "fulltext"), f"Unknown mode: {mode}"
    prompt_type = PROMPT_TYPE_ABSTRACT if mode == "abstract" else PROMPT_TYPE_FULLTEXT
    
    try:
        with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and prompt_type in data:
            return str(data[prompt_type])
        # If PROMPT_TYPE is not a key, use the full JSON as fallback string
        return str(data)
    except Exception:
        return "Please classify whether this study matches the review criteria."