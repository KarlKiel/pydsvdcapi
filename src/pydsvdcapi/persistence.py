# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
"""YAML-based persistence for vDC host state.

Stores the complete property tree of a vDC host (including its vDCs and
vdSDs) in a human-readable YAML file.  A backup copy (``<file>.bak``) is
maintained automatically so that a corrupt primary file can be recovered.

Write strategy (atomic with backup):
  1. If the current YAML file exists, copy it to ``<file>.bak``.
  2. Write a *new* temporary file (``<file>.tmp``) next to the target.
  3. ``os.replace`` the temporary file onto the target — this is an
     atomic operation on POSIX systems (and best-effort on Windows).

Load strategy (with fallback):
  1. Try to load the primary YAML file.
  2. If that fails (missing, corrupt, permissions), try ``<file>.bak``.
  3. If the backup also fails, return ``None`` so callers can start
     fresh.

Usage example::

    from pydsvdcapi.persistence import PropertyStore

    store = PropertyStore("/var/lib/myvdc/state.yaml")

    # Save
    store.save(host.get_property_tree())

    # Load (returns None when no state exists yet)
    tree = store.load()
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Type alias for a nested property tree.
PropertyTree = dict[str, Any]

# Suffix appended to the primary file for the backup copy.
_BACKUP_SUFFIX = ".bak"
# Suffix for the temporary file used during atomic writes.
_TMP_SUFFIX = ".tmp"


class PropertyStore:
    """YAML-backed property store with automatic backup / recovery.

    Parameters
    ----------
    path:
        Path to the primary YAML file.  Parent directories are created
        automatically on first :meth:`save`.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._backup_path = self._path.with_suffix(self._path.suffix + _BACKUP_SUFFIX)
        self._tmp_path = self._path.with_suffix(self._path.suffix + _TMP_SUFFIX)

    # ---- public properties -------------------------------------------

    @property
    def path(self) -> Path:
        """The primary YAML file path."""
        return self._path

    @property
    def backup_path(self) -> Path:
        """The backup file path (``<path>.bak``)."""
        return self._backup_path

    # ---- save ---------------------------------------------------------

    def save(self, tree: PropertyTree) -> None:
        """Persist *tree* to the YAML file (with backup).

        Parameters
        ----------
        tree:
            Nested dictionary representing the full property tree.

        Raises
        ------
        OSError
            If the file cannot be written.
        """
        # Ensure the parent directory exists.
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Back up the current file (if it exists).
        if self._path.is_file():
            try:
                shutil.copy2(str(self._path), str(self._backup_path))
                logger.debug("Backed up %s → %s", self._path, self._backup_path)
            except OSError:
                logger.warning(
                    "Failed to create backup %s — continuing anyway.",
                    self._backup_path,
                )

        # 2. Write to a temporary file first.
        try:
            with open(self._tmp_path, "w", encoding="utf-8") as fh:
                yaml.dump(
                    tree,
                    fh,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
        except OSError:
            logger.error("Failed to write temporary file %s", self._tmp_path)
            raise

        # 3. Atomically replace the target with the temp file.
        try:
            os.replace(str(self._tmp_path), str(self._path))
        except OSError:
            logger.error("Failed to replace %s with %s", self._path, self._tmp_path)
            raise

        logger.info("Saved property tree to %s", self._path)

    # ---- load ---------------------------------------------------------

    def load(self) -> PropertyTree | None:
        """Load the property tree from YAML (primary, then backup).

        Returns
        -------
        PropertyTree or None
            The restored property tree, or ``None`` if neither the
            primary file nor the backup could be loaded.
        """
        # Try primary file first.
        tree = self._try_load(self._path)
        if tree is not None:
            return tree

        # Fall back to backup.
        logger.warning(
            "Primary file %s not usable — trying backup %s",
            self._path,
            self._backup_path,
        )
        tree = self._try_load(self._backup_path)
        if tree is not None:
            # Restore the primary from the backup so next save has a
            # clean base.
            try:
                shutil.copy2(str(self._backup_path), str(self._path))
                logger.info(
                    "Restored primary file from backup: %s → %s",
                    self._backup_path,
                    self._path,
                )
            except OSError:
                logger.warning("Could not restore primary from backup.")
            return tree

        logger.info("No persisted state found — starting fresh.")
        return None

    # ---- delete -------------------------------------------------------

    def delete(self) -> None:
        """Remove both the primary and backup files (if they exist)."""
        for p in (self._path, self._backup_path, self._tmp_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove %s", p)

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _try_load(path: Path) -> PropertyTree | None:
        """Attempt to load and parse a single YAML file.

        Returns ``None`` on any failure (missing, unreadable, corrupt).
        """
        if not path.is_file():
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Failed to load %s: %s", path, exc)
            return None

        if not isinstance(data, dict):
            logger.warning(
                "Expected a mapping at top level in %s, got %s",
                path,
                type(data).__name__,
            )
            return None

        return data

    # ---- dunder -------------------------------------------------------

    def __repr__(self) -> str:
        return f"PropertyStore({str(self._path)!r})"
