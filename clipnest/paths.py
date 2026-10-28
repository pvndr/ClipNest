"""Where ClipNest keeps its per-user data.

The database and the preference store live next to each other in the current
Windows user's application-data directory (``%LOCALAPPDATA%/ClipNest``), never
in the source tree or next to the executable, so a packaged build and a
development run share the same history for the same account.

``CLIPNEST_DATA_DIR`` redirects both of them to an absolute directory. That is
how a packaged build is exercised without reading or writing the history and
preferences of the account running the check, and it is also what a portable
install would use. The variable is never required: without it the documented
application-data location is used.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths

logger = logging.getLogger(__name__)

DATA_DIR_ENV = "CLIPNEST_DATA_DIR"
APP_FOLDER_NAME = "ClipNest"
DATABASE_FILENAME = "clipnest.db"
SETTINGS_FILENAME = "settings.ini"


def data_dir_override() -> Path | None:
    """Return the directory named by ``CLIPNEST_DATA_DIR``, or ``None``.

    Only an absolute path is honoured: a relative value would put the database
    wherever the process happens to start, which is exactly what the
    application-data default exists to avoid. The directory is created here so
    callers can use it immediately.
    """
    raw = os.environ.get(DATA_DIR_ENV, "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        logger.warning(
            "%s must be an absolute path; ignoring %r", DATA_DIR_ENV, raw
        )
        return None
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning(
            "%s could not be created; using the default data directory",
            candidate,
        )
        return None
    return candidate


def default_data_dir() -> Path | None:
    """Return the platform's per-user data directory, or ``None``.

    On Windows ``GenericDataLocation`` resolves to ``%LOCALAPPDATA%``.
    ``AppDataLocation`` is avoided because the organisation and application
    names are both "ClipNest", which would nest the files under
    ``.../ClipNest/ClipNest``.
    """
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericDataLocation
    )
    if not base:
        return None
    return Path(base) / APP_FOLDER_NAME


def data_dir() -> Path | None:
    """The directory ClipNest stores its data in, or ``None`` when unknown."""
    override = data_dir_override()
    if override is not None:
        return override
    return default_data_dir()


def database_path() -> Path | None:
    """The full path of the clipboard database, or ``None`` when unknown."""
    base = data_dir()
    if base is None:
        return None
    return base / DATABASE_FILENAME


def settings_path() -> Path | None:
    """The INI file used when the data directory is overridden."""
    override = data_dir_override()
    if override is None:
        return None
    return override / SETTINGS_FILENAME
