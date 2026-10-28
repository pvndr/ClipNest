"""Diagnostics for a packaged build: one small, content-free log file.

Every logger call in ClipNest records an event, never clipboard text: the
capture pipeline logs the skip *reason*, the storage layer logs failures
without the snippet, and the tray logs icon trouble. The file exists because a
release build has no console, so without it a problem would leave no trace at
all to look at.

The log lives next to the clipboard database, rotates at :data:`LOG_MAX_BYTES`
and keeps one backup. When it cannot be opened (read-only profile, missing
directory) logging stays silent: diagnostics must never stop the application
from starting.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from clipnest import paths

LOG_FILENAME = "clipnest.log"
LOG_MAX_BYTES = 256 * 1024
LOG_BACKUPS = 1
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

_configured = False
_configured_path: Path | None = None


def configure_logging(
    directory: Path | None = None, level: int = logging.INFO
) -> Path | None:
    """Attach the log file and return its path, or ``None`` when unavailable.

    ``directory`` defaults to the application data directory. A console stream
    is added only when the process actually has one, which keeps a ``--noconsole``
    build from writing into a handle that does not exist. Calling twice is
    harmless: the configuration is applied once per process.
    """
    global _configured, _configured_path
    if _configured:
        return _configured_path
    _configured = True

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)

    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    target = directory if directory is not None else paths.data_dir()
    if target is None:
        root.warning("No writable data directory; logging to the console only")
        return None

    try:
        target.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            target / LOG_FILENAME,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS,
            encoding="utf-8",
        )
    except OSError:
        root.warning("The log file could not be opened; continuing without it")
        return None

    handler.setFormatter(formatter)
    root.addHandler(handler)
    _configured_path = target / LOG_FILENAME
    return _configured_path


def log_path() -> Path | None:
    """The log file in use, or ``None`` when logging went to the console only."""
    return _configured_path
