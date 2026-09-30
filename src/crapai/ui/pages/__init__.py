"""One module per page. Each has ``render(st, ctx)`` and draws with the Streamlit module ``st``.

``st`` is passed in instead of imported so that importing a page never needs Streamlit; tests use
Streamlit's ``AppTest`` to run them for real.
"""
