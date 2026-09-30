"""The project folder layout and its schema version (plan chapter 6).

A review project is a folder; the folder is the database. This module creates the standard
sub-folders, records the schema version in ``.crapai/version`` and refuses to open folders that are
not projects or that need a migration (error E404). The state folder is ``.crapai/`` (ADR 0017).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from crapai.branding import STATE_DIR_NAME
from crapai.errors import StorageError
from crapai.project.atomic import atomic_write_text
from crapai.project.lock import ProjectLock

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
LEGACY_STATE_DIR_NAME = ".sara"  # working name before ADR 0017; only used to give a helpful error
SYNC_FOLDER_MARKERS = ("onedrive", "dropbox", "sharepoint")


def cloud_sync_hint(path: Path) -> str | None:
    """Return a warning text if ``path`` lies in a synchronised folder, else None.

    Sync clients touch files while they are written and create conflict copies, so active runs
    should live in a non-synchronised folder (plan chapter 28.9).
    """
    lowered = [part.lower() for part in path.resolve().parts]
    for marker in SYNC_FOLDER_MARKERS:
        if any(marker in part for part in lowered):
            return (
                f"The project folder is inside a synchronised location ({marker}). "
                "Run screening in a non-synchronised folder and archive it afterwards."
            )
    return None


@dataclass(frozen=True)
class Workspace:
    """Paths inside one project folder. Creating the object does not touch the disk."""

    root: Path

    # -- files -----------------------------------------------------------------------------
    @property
    def project_yaml(self) -> Path:
        """``project.yaml``: the project configuration."""
        return self.root / "project.yaml"

    @property
    def records_csv(self) -> Path:
        """``data/records.csv``: all records (the single source of truth)."""
        return self.data_dir / "records.csv"

    @property
    def import_log(self) -> Path:
        """``data/records.import.jsonl``: one entry per imported file."""
        return self.data_dir / "records.import.jsonl"

    @property
    def events_jsonl(self) -> Path:
        """``data/events.jsonl``: the PRISMA event stream of the project (append-only)."""
        return self.data_dir / "events.jsonl"

    @property
    def version_file(self) -> Path:
        """``.crapai/version``: the schema version of the project folder."""
        return self.state_dir / "version"

    @property
    def lock_file(self) -> Path:
        """``.crapai/lock``: the single-writer lock."""
        return self.state_dir / "lock"

    @property
    def app_log(self) -> Path:
        """``.crapai/app.log``: the technical log (no record contents)."""
        return self.state_dir / "app.log"

    @property
    def pricing_csv(self) -> Path:
        """``pricing.csv``: the user's price list (optional; example in templates/)."""
        return self.root / "pricing.csv"

    # -- folders ---------------------------------------------------------------------------
    @property
    def sources_dir(self) -> Path:
        """``sources/``: unchanged copies of the imported files."""
        return self.root / "sources"

    @property
    def data_dir(self) -> Path:
        """``data/``: records, import log and backups."""
        return self.root / "data"

    @property
    def backup_dir(self) -> Path:
        """``data/.backup/``: the last five copies of ``records.csv``."""
        return self.data_dir / ".backup"

    @property
    def runs_dir(self) -> Path:
        """``runs/``: one folder per screening run (planned)."""
        return self.root / "runs"

    @property
    def human_dir(self) -> Path:
        """``human/``: human decisions for the evaluation (planned)."""
        return self.root / "human"

    @property
    def reports_dir(self) -> Path:
        """``reports/``: statistics and reports (planned)."""
        return self.root / "reports"

    @property
    def prompts_dir(self) -> Path:
        """``prompts/``: optional own prompt variants (planned)."""
        return self.root / "prompts"

    @property
    def state_dir(self) -> Path:
        """``.crapai/``: technical state of the project (version, lock, log)."""
        return self.root / STATE_DIR_NAME

    def folders(self) -> tuple[Path, ...]:
        """All sub-folders that :meth:`create` makes (the backup folder is created on demand)."""
        return (
            self.sources_dir,
            self.data_dir,
            self.runs_dir,
            self.human_dir,
            self.reports_dir,
            self.prompts_dir,
            self.state_dir,
        )

    # -- lifecycle -------------------------------------------------------------------------
    @classmethod
    def create(cls, root: Path) -> Workspace:
        """Create a new project folder (the folder itself may exist if it is empty).

        Raises:
            StorageError: (E404) if ``root`` already is a project or contains other files.
        """
        workspace = cls(root)
        if workspace.version_file.exists():
            raise StorageError(
                f"{root} is already a project folder",
                code="E404",
                hint="Open the existing project or choose another folder.",
                details={"path": str(root)},
            )
        if root.exists() and any(root.iterdir()):
            raise StorageError(
                f"{root} exists and is not empty",
                code="E404",
                hint="Choose a new or empty folder for the project.",
                details={"path": str(root)},
            )
        for folder in workspace.folders():
            folder.mkdir(parents=True, exist_ok=True)
        atomic_write_text(workspace.version_file, f"{SCHEMA_VERSION}\n")
        _warn_if_synchronised(root)
        logger.info("Created project folder %s (schema %d)", root, SCHEMA_VERSION)
        return workspace

    @classmethod
    def open(cls, root: Path) -> Workspace:
        """Open an existing project folder and check its schema version.

        Raises:
            StorageError: (E404) if ``root`` is not a project, or its schema version is not the
                one this program understands (``crapai migrate`` is the planned remedy).
        """
        workspace = cls(root)
        version = workspace.read_version()
        if version != SCHEMA_VERSION:
            raise StorageError(
                f"The project folder has schema version {version}, this program needs "
                f"{SCHEMA_VERSION}",
                code="E404",
                hint="Migrate the project with 'crapai migrate' or use a matching program version.",
                details={"path": str(root), "found": version, "expected": SCHEMA_VERSION},
            )
        _warn_if_synchronised(root)
        return workspace

    def read_version(self) -> int:
        """Return the schema version stored in ``.crapai/version``.

        Raises:
            StorageError: (E404) if the file is missing or does not contain an integer.
        """
        try:
            text = self.version_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            if (self.root / LEGACY_STATE_DIR_NAME / "version").exists():
                raise StorageError(
                    f"{self.root} was created with a pre-release name: the state folder "
                    f"{LEGACY_STATE_DIR_NAME} is now called {STATE_DIR_NAME}",
                    code="E404",
                    hint=f"Rename {LEGACY_STATE_DIR_NAME} to {STATE_DIR_NAME} in the project.",
                    details={"path": str(self.root), "legacy": LEGACY_STATE_DIR_NAME},
                ) from None
            raise StorageError(
                f"{self.root} is not a project folder (no {STATE_DIR_NAME}/version)",
                code="E404",
                hint="Create a project with 'crapai init' or select the correct folder.",
                details={"path": str(self.root)},
            ) from None
        try:
            return int(text)
        except ValueError:
            raise StorageError(
                f"The version file of {self.root} is damaged",
                code="E404",
                hint="Restore .crapai/version from a backup.",
                details={"path": str(self.version_file)},
            ) from None

    def lock(self) -> ProjectLock:
        """Return the (not yet acquired) lock object of this project."""
        return ProjectLock(self.lock_file)


def _warn_if_synchronised(root: Path) -> None:
    hint = cloud_sync_hint(root)
    if hint:
        logger.warning(hint)
