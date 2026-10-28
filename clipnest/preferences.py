"""User preferences, persisted with :class:`QSettings`.

What is stored: the appearance choice, the retention limits, the sensitive-
content policy, the pause state, and the one-time monitoring notice flag.
Everything is read once at startup, before the window and the clipboard
monitor exist, so a restart reproduces the same behaviour. Nothing here
touches the clipboard, the database, or the network.

Stored values are treated as untrusted: a hand-edited or stale registry entry
falls back to the defaults instead of raising during startup. The pause state
is the one exception that reports failure explicitly (``None``) instead of
quietly choosing a default, because resuming capture behind the user's back
would be a privacy decision this module is not allowed to make.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSettings

from clipnest import paths
from clipnest.core.storage import (
    DEFAULT_HISTORY_LIMIT,
    validate_retention_days,
)
from clipnest.ui.theme import DARK, THEMES

logger = logging.getLogger(__name__)

ORGANISATION = "ClipNest"
APPLICATION = "ClipNest"

THEME_KEY = "appearance/theme"
HISTORY_LIMIT_KEY = "history/limit"
RETENTION_DAYS_KEY = "history/retention_days"
SENSITIVE_DETECTION_KEY = "privacy/sensitive_detection"
PAUSED_KEY = "capture/paused"
MONITORING_NOTICE_KEY = "notices/monitoring_shown"

DEFAULT_THEME = DARK.name
DEFAULT_SENSITIVE_DETECTION = True
DEFAULT_RETENTION_DAYS: int | None = None
DEFAULT_PAUSED = False
DEFAULT_MONITORING_NOTICE_SHOWN = False
MIN_HISTORY_LIMIT = 10
MAX_HISTORY_LIMIT = 5_000


def validate_history_limit(value: object) -> int:
    """Return ``value`` as a valid retention limit, or raise :class:`ValueError`."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("The history limit must be a whole number.")
    if not MIN_HISTORY_LIMIT <= value <= MAX_HISTORY_LIMIT:
        raise ValueError(
            f"Choose between {MIN_HISTORY_LIMIT:,} and {MAX_HISTORY_LIMIT:,} "
            "unpinned snippets."
        )
    return value


def default_settings() -> QSettings:
    """Return the per-user QSettings store (Windows registry by default).

    When ``CLIPNEST_DATA_DIR`` is set, the store is an INI file in that
    directory instead, so an isolated run cannot change the real account's
    preferences either.
    """
    settings_file = paths.settings_path()
    if settings_file is not None:
        return QSettings(str(settings_file), QSettings.Format.IniFormat)
    return QSettings(
        QSettings.Format.NativeFormat,
        QSettings.Scope.UserScope,
        ORGANISATION,
        APPLICATION,
    )


class Preferences:
    """Typed accessors over one QSettings store."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else default_settings()

    # ------------------------------------------------------------------ theme

    def theme(self) -> str:
        """Return the stored theme name, or the default when it is unusable."""
        stored = str(self._settings.value(THEME_KEY, DEFAULT_THEME)).strip().lower()
        if stored not in THEMES:
            logger.warning("Unknown stored theme %r; using %r", stored, DEFAULT_THEME)
            return DEFAULT_THEME
        return stored

    def set_theme(self, mode: str) -> None:
        """Persist ``mode``; unknown names are rejected rather than stored."""
        if mode not in THEMES:
            raise ValueError(f"Unknown theme: {mode!r}")
        self._settings.setValue(THEME_KEY, mode)
        self._settings.sync()

    # ---------------------------------------------------------------- history

    def history_limit(self) -> int:
        """Return the stored retention limit, or the default when unusable."""
        stored = self._settings.value(HISTORY_LIMIT_KEY, DEFAULT_HISTORY_LIMIT)
        try:
            return validate_history_limit(int(stored))
        except (TypeError, ValueError):
            logger.warning(
                "Stored history limit %r is not usable; using %d",
                stored,
                DEFAULT_HISTORY_LIMIT,
            )
            return DEFAULT_HISTORY_LIMIT

    def set_history_limit(self, limit: int) -> None:
        """Persist a validated retention limit."""
        self._settings.setValue(HISTORY_LIMIT_KEY, validate_history_limit(limit))
        self._settings.sync()

    # --------------------------------------------------------------- retention

    def retention_days(self) -> int | None:
        """Age limit in days, or ``None`` when age-based expiry is disabled."""
        stored = self._settings.value(RETENTION_DAYS_KEY, "")
        text_value = str(stored).strip().lower()
        if text_value in ("", "0", "none", "disabled", "off", "false"):
            return DEFAULT_RETENTION_DAYS
        try:
            return validate_retention_days(int(text_value))
        except (TypeError, ValueError):
            logger.warning(
                "Stored age limit %r is not usable; age-based expiry stays off",
                stored,
            )
            return DEFAULT_RETENTION_DAYS

    def set_retention_days(self, days: int | None) -> None:
        """Persist the age limit (``None`` disables it)."""
        value = validate_retention_days(days)
        self._settings.setValue(RETENTION_DAYS_KEY, "" if value is None else value)
        self._settings.sync()

    # ---------------------------------------------------------------- privacy

    def sensitive_detection_enabled(self) -> bool:
        """Whether sensitive-content detection is on (it is on by default)."""
        return _stored_bool(
            self._settings,
            SENSITIVE_DETECTION_KEY,
            DEFAULT_SENSITIVE_DETECTION,
            "sensitive-detection setting",
        )

    def set_sensitive_detection(self, enabled: bool) -> None:
        """Persist the sensitive-content policy."""
        self._settings.setValue(SENSITIVE_DETECTION_KEY, bool(enabled))
        self._settings.sync()

    # ------------------------------------------------------------- monitoring

    def monitoring_paused(self) -> bool | None:
        """The saved pause state, or ``None`` when a stored value is unusable.

        ``None`` means "a value is stored, but it cannot be read". The
        composition root starts paused in that case: a corrupt preference must
        never resume capturing text the user asked ClipNest not to keep.
        """
        stored = self._settings.value(PAUSED_KEY, None)
        if stored is None:
            return DEFAULT_PAUSED
        if isinstance(stored, bool):
            return stored
        parsed = _parse_bool(str(stored))
        if parsed is None:
            logger.warning(
                "Stored pause state %r is not usable; starting paused", stored
            )
        return parsed

    def set_monitoring_paused(self, paused: bool) -> None:
        """Persist the pause state so a restart starts the same way."""
        self._settings.setValue(PAUSED_KEY, bool(paused))
        self._settings.sync()

    def monitoring_notice_shown(self) -> bool:
        """Whether the one-time monitoring notice has already been shown."""
        return _stored_bool(
            self._settings,
            MONITORING_NOTICE_KEY,
            DEFAULT_MONITORING_NOTICE_SHOWN,
            "monitoring notice flag",
        )

    def set_monitoring_notice_shown(self, shown: bool) -> None:
        """Persist that the monitoring notice has been shown."""
        self._settings.setValue(MONITORING_NOTICE_KEY, bool(shown))
        self._settings.sync()


_TRUE_TEXT = ("true", "1", "yes", "on")
_FALSE_TEXT = ("false", "0", "no", "off")


def _parse_bool(text: str) -> bool | None:
    """Interpret a stored boolean, or return ``None`` when it is unusable."""
    normalised = text.strip().lower()
    if normalised in _TRUE_TEXT:
        return True
    if normalised in _FALSE_TEXT:
        return False
    return None


def _stored_bool(
    settings: QSettings, key: str, default: bool, label: str
) -> bool:
    """Read a boolean, falling back to ``default`` when it is unusable."""
    stored = settings.value(key, default)
    if isinstance(stored, bool):
        return stored
    parsed = _parse_bool(str(stored))
    if parsed is not None:
        return parsed
    logger.warning("Stored %s %r is not usable; using %r", label, stored, default)
    return default