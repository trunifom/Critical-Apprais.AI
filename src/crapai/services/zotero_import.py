"""Pull a Zotero library or collection into a project, read-only (ADR 0030).

Reuses the ordinary import pipeline wholesale instead of reimplementing it: the text Zotero
returns is written to a real file under ``sources/`` first, then imported through the existing
:func:`crapai.services.importing.import_source` exactly like any file a user uploads -- hashing,
the import log (``E106`` for a repeat), the backup and the atomic write all keep working unchanged.

There is no "already synced" tracking here. A repeat sync rarely produces byte-identical text (item
order and timestamps change), so the import log's hash check will not recognise it as a repeat --
but that is harmless: the project's existing duplicate detection (``crapai dedup``, by DOI/title)
marks the re-imported, already-known records as ``DUPLICATE`` exactly as it would for any other
repeated bibliographic export.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from crapai.config.loader import load_project_config
from crapai.config.models import ZoteroSettings
from crapai.errors import AuthError
from crapai.project.workspace import Workspace
from crapai.services.importing import ImportRequest, ImportSummary, import_source
from crapai.zotero.client import MockZoteroClient, ZoteroClient

logger = logging.getLogger(__name__)


def build_client(
    settings: ZoteroSettings, environ: dict[str, str] | None = None
) -> ZoteroClient | MockZoteroClient:
    """The Zotero client named by ``settings``.

    Raises:
        AuthError: E301 if ``api_key_env`` names a variable that is not set (a non-empty
            ``api_key_env`` is assumed to be required; leave it empty for a public library).
        ProviderError: E305 if the ``httpx`` package is missing.
    """
    key = ""
    if settings.api_key_env:
        env = environ if environ is not None else os.environ
        key = env.get(settings.api_key_env, "").strip()
        if not key:
            hint = f"Set {settings.api_key_env} to the Zotero API key (never stored in the project)"
            message = f"The environment variable {settings.api_key_env} is not set"
            raise AuthError(message, code="E301", hint=hint)
    return ZoteroClient(
        key,
        library_type=settings.library_type,
        library_id=settings.library_id,
        collection_key=settings.collection_key,
    )


def zotero_import_project(
    workspace: Workspace,
    *,
    label: str = "Zotero",
    force: bool = False,
    client: ZoteroClient | MockZoteroClient | None = None,
    now: datetime | None = None,
) -> ImportSummary:
    """Fetch the configured library/collection and import it like any other file.

    Raises:
        AuthError: E301 if the API key is missing.
        ImportFailed: E101/E102 if the library/collection is unknown or empty; E106 for a
            byte-identical repeat (rare -- see the module docstring) unless ``force``.
        StorageError: E402 if the project is in use, E404 for a damaged folder, E401/E403 for
            write problems.
    """
    workspace = Workspace.open(workspace.root)
    settings = load_project_config(workspace.project_yaml).zotero
    chosen_client = client or build_client(settings)
    try:
        text = chosen_client.fetch_text(format=settings.format)
    finally:
        if client is None:
            chosen_client.close()
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    extension = "bib" if settings.format == "bibtex" else "ris"
    name = f"zotero-{settings.library_id or 'library'}-{stamp}.{extension}"
    path = workspace.sources_dir / name
    workspace.sources_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    logger.info("Zotero: fetched %d character(s), importing as %s", len(text), name)
    return import_source(workspace, ImportRequest(path, label=label, force=force), now=now)
