"""Entry point that Streamlit runs: ``streamlit run streamlit_app.py`` (or ``crapai ui``)."""

import streamlit as st

from crapai.ui.app import main

main(st)
