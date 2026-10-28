"""Application icon lookup for the window, taskbar and system tray.

The ClipNest artwork is a supplied asset, not something this app draws: no icon
is generated, downloaded or substituted here. When the file is missing or
unreadable the callers stay icon-less and the expected path is logged, so a
missing asset is reported instead of being silently papered over with a
placeholder.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtGui import QIcon

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"

#: Canonical asset location, as documented in the README.
APP_ICON_PATH = ASSETS_DIR / "clipnest.ico"

#: Accepted alternative, tried after :data:`APP_ICON_PATH`.
FALLBACK_ICON_PATHS: tuple[Path, ...] = (ASSETS_DIR / "clipnest_icon_transparent.png",)

#: Size used to prove a candidate file decodes into a real bitmap.
PREVIEW_SIZE = 64


def icon_candidates() -> tuple[Path, ...]:
    """Return the asset paths searched for the application icon, in order."""
    return (APP_ICON_PATH, *FALLBACK_ICON_PATHS)


def load_app_icon(candidates: Iterable[Path] | None = None) -> QIcon | None:
    """Return the first decodable icon asset, or ``None`` when none is present.

    ``candidates`` exists so tests can point at a fixture file without touching
    the real asset directory.
    """
    paths = icon_candidates() if candidates is None else tuple(candidates)
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        icon = QIcon(str(path))
        # A filename-backed QIcon is never "null" even for a corrupt file, so
        # decode one frame to tell a real asset apart from a broken one.
        if icon.isNull() or icon.pixmap(PREVIEW_SIZE, PREVIEW_SIZE).isNull():
            logger.warning("Icon asset %s exists but could not be decoded", path)
            continue
        return icon
    return None


def report_missing_icon() -> None:
    """Log where the icon is expected, and what its absence switches off."""
    logger.warning(
        "No application icon asset found; expected %s - the window stays "
        "icon-less and the system tray is disabled until it exists",
        APP_ICON_PATH,
    )
