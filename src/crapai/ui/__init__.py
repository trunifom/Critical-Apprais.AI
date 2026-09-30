"""The local interface (Streamlit). Start it with ``crapai ui``; it needs the ``ui`` extra.

Layers of this package:

``viewmodels``
    What is shown, decided without Streamlit (stepper, status bar, recent projects). Plain tests.
``actions``
    What a click does: calls the services, turns every failure into an ``ErrorReport``. Plain tests.
``pages``
    The drawing itself, one module per page. Tested with Streamlit's ``AppTest``.
``app``
    The entry point that Streamlit runs: page setup, language, navigation, status bar.

Only ``pages`` and ``app`` import Streamlit, and only lazily where a page is drawn, so the rest of
the package can be imported and tested without it.
"""
