"""Application bootstrap: services, QApplication setup, and window lifecycle.

Composition happens here and nowhere else: the repository and clipboard
service are constructed first and injected into the window, while the tray is
wired to both. Closing the window hides it to the tray when the platform has
one; every other path (no tray, Quit menu, app shutdown) still ends cleanly.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QClipboard, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from clipnest import __version__
from clipnest.core.clipboard import DEFAULT_MAX_TEXT_LENGTH, ClipboardService
from clipnest.core.clipboard_flags import (
    ClipboardFlagsProvider,
    default_flags_provider,
)
from clipnest.core.protection import TextProtector, default_text_protector
from clipnest.core.storage import (
    DEFAULT_HISTORY_LIMIT,
    ClipboardRepository,
    StorageError,
)
from clipnest.logging_setup import configure_logging
from clipnest.preferences import Preferences
from clipnest.ui.app_icon import load_app_icon, report_missing_icon
from clipnest.ui.main_window import MainWindow
from clipnest.ui.theme import DARK, apply_theme
from clipnest.ui.tray import TrayIcon

APP_NAME = "ClipNest"
ORG_NAME = "ClipNest"

MAX_TEXT_LENGTH = DEFAULT_MAX_TEXT_LENGTH
HISTORY_LIMIT = DEFAULT_HISTORY_LIMIT

TRAY_CHECK_INTERVAL_MS = 5_000
# Consecutive failed checks before the tray is treated as gone for good: a
# normal Explorer restart comes back within a few seconds.
TRAY_LOST_PATIENCE = 3

logger = logging.getLogger(__name__)


def create_application(
    argv: list[str] | None = None, theme_mode: str = DARK.name
) -> QApplication:
    """Create the QApplication with app metadata and the requested theme."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)
    apply_theme(app, theme_mode)
    return app


def create_repository(
    database_path: str | Path | None = None,
    history_limit: int = HISTORY_LIMIT,
    retention_days: int | None = None,
    protector: TextProtector | None = None,
) -> ClipboardRepository:
    """Build the SQLite repository (app-data location unless overridden).

    The at-rest protector is injected here, in the composition root, so the
    repository itself never chooses between encryption and plaintext: the
    application always gets Windows DPAPI, and tests inject their own.
    """
    return ClipboardRepository(
        database_path=database_path,
        history_limit=history_limit,
        retention_days=retention_days,
        protector=(
            protector if protector is not None else default_text_protector()
        ),
    )


def create_clipboard_service(
    clipboard: QClipboard,
    repository: ClipboardRepository,
    max_text_length: int = MAX_TEXT_LENGTH,
    flags_provider: ClipboardFlagsProvider | None = None,
    sensitive_detector=None,
    sensitive_enabled: bool = True,
    paused: bool = False,
) -> ClipboardService:
    """Build the clipboard monitor for the given clipboard and repository.

    The Windows privacy-marker provider is injected here, in the composition
    root, so the service itself never loads native APIs and tests can pass an
    inert provider instead. ``paused`` carries the saved pause state into the
    constructor, which applies it before the service starts listening.
    """
    return ClipboardService(
        clipboard=clipboard,
        repository=repository,
        max_text_length=max_text_length,
        flags_provider=(
            flags_provider if flags_provider is not None else default_flags_provider()
        ),
        sensitive_detector=sensitive_detector,
        sensitive_enabled=sensitive_enabled,
        paused=paused,
    )


def read_startup_pause(preferences: Preferences) -> tuple[bool, bool]:
    """Resolve the saved pause state before monitoring starts.

    Returns ``(paused, unreadable)``. A stored value that cannot be interpreted
    starts ClipNest paused and reports ``unreadable`` so the window can say why:
    silently resuming capture would override a privacy choice the user made.
    """
    stored = preferences.monitoring_paused()
    if stored is None:
        logger.warning("Saved pause state could not be read; starting paused")
        return True, True
    return stored, False


def create_main_window(
    repository: ClipboardRepository,
    clipboard_service: ClipboardService,
    window_icon: QIcon | None = None,
    preferences: Preferences | None = None,
) -> MainWindow:
    """Build the main window with its dependencies injected."""
    return MainWindow(
        repository=repository,
        clipboard_service=clipboard_service,
        window_icon=window_icon,
        preferences=preferences,
    )


def create_tray_icon(icon: QIcon | None = None) -> TrayIcon | None:
    """Build and show the tray icon, or ``None`` when the tray is unusable.

    Tray support is optional, and an image-less tray is not a usable control
    panel (the shell shows nothing to right-click), so a missing icon asset
    counts as "no tray" as well: the window keeps its normal close-to-quit
    behaviour and the application can always be closed.
    """
    if icon is None:
        logger.warning("Tray disabled: a tray icon needs an image asset")
        return None
    if not QSystemTrayIcon.isSystemTrayAvailable():
        logger.info("No system tray available; ClipNest will close normally")
        return None
    try:
        tray = TrayIcon(icon=icon)
        tray.show()
    except RuntimeError as exc:
        logger.warning("System tray icon could not be created: %s", exc)
        return None
    if not tray.isVisible():
        logger.warning("System tray icon did not become visible; tray disabled")
        tray.hide()
        return None
    logger.info("System tray icon is active")
    return tray


class TrayWatchdog(QObject):
    """Periodically re-asserts the tray icon and keeps ClipNest escapable.

    Qt's Windows backend re-adds the icon itself when the shell broadcasts its
    taskbar-recreated message, so calling ``recover`` on a healthy tray only
    updates the icon this process already owns. What Qt cannot do is outlive a
    shell that never comes back, and a tray-only application whose icon is gone
    while the window hides on close has no way out. After
    :data:`TRAY_LOST_PATIENCE` consecutive failures the fallback runs once and
    watching stops, so a brief Explorer restart never costs the user the tray.
    """

    def __init__(
        self,
        recover: Callable[[], bool],
        on_lost: Callable[[], None],
        interval_ms: int = TRAY_CHECK_INTERVAL_MS,
        patience: int = TRAY_LOST_PATIENCE,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._recover = recover
        self._on_lost = on_lost
        self._patience = max(1, patience)
        self._failures = 0
        self._gave_up = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.check_now)

    @property
    def is_watching(self) -> bool:
        """Whether periodic shell checks are scheduled."""
        return self._timer.isActive()

    @property
    def gave_up(self) -> bool:
        """Whether the icon was declared lost and the fallback ran."""
        return self._gave_up

    def start(self) -> None:
        """Begin watching. Starting twice keeps a single timer."""
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """Stop watching."""
        self._timer.stop()

    def check_now(self) -> bool:
        """Run one check and return whether the tray is still usable."""
        if self._gave_up:
            return False
        if self._recover():
            self._failures = 0
            return True
        self._failures += 1
        if self._failures < self._patience:
            return True
        self._gave_up = True
        self.stop()
        logger.warning("Tray icon could not be restored; enabling close-to-quit")
        self._on_lost()
        return False


def wire_tray(
    tray: TrayIcon,
    window: MainWindow,
    clipboard_service: ClipboardService,
    app: QApplication,
) -> "TrayWatchdog":
    """Connect the tray menu to the window and the clipboard service.

    Monitoring state flows one way only: the clipboard service is the single
    source of truth, and both the window button and the tray action follow its
    ``paused_changed`` signal, so the two can never disagree.

    Returns the watchdog that guards the icon itself. It is wired but not
    started here, so a caller decides when periodic shell checks begin (tests
    never arm it).
    """
    window.set_hide_on_close(True)
    # The window is hidden, not closed, but the guard keeps a closed dialog
    # from ending the session while the tray is alive.
    app.setQuitOnLastWindowClosed(False)

    tray.show_requested.connect(window.show_from_tray)
    tray.pause_toggled.connect(window.toggle_monitoring)
    tray.clear_requested.connect(window.clear_unpinned_history)
    tray.quit_requested.connect(lambda: quit_application(app, clipboard_service))
    window.hidden_to_tray.connect(tray.notify_hidden_once)

    clipboard_service.paused_changed.connect(tray.set_paused)
    tray.set_paused(clipboard_service.is_paused)

    # Never leave a ghost icon behind once the event loop is gone.
    app.aboutToQuit.connect(tray.hide)

    return TrayWatchdog(
        recover=tray.recover,
        on_lost=lambda: restore_close_to_quit(app, window),
        parent=tray,
    )


def restore_close_to_quit(app: QApplication, window: MainWindow) -> None:
    """Keep ClipNest reachable after the tray icon could not be restored."""
    window.fall_back_from_tray()
    if window.isHidden():
        # The tray was the only way back to a hidden window, so it has to
        # become visible again or the running application would be stranded.
        window.show_from_tray()
    app.setQuitOnLastWindowClosed(True)


def quit_application(
    app: QApplication, clipboard_service: ClipboardService
) -> None:
    """Stop monitoring, then ask the event loop to exit."""
    logger.info("Quit requested from the system tray")
    clipboard_service.stop()
    app.quit()


def main(argv: list[str] | None = None) -> int:
    """Run the ClipNest desktop application and return its exit code."""
    log_file = configure_logging()
    logger.info("ClipNest %s starting", __version__)
    if log_file is not None:
        logger.info("Log file: %s", log_file)

    preferences = Preferences()
    # The saved appearance is applied before any window exists, so the first
    # paint is already in the right theme.
    app = create_application(argv, theme_mode=preferences.theme())

    try:
        repository = create_repository(
            history_limit=preferences.history_limit(),
            retention_days=preferences.retention_days(),
        )
    except StorageError as exc:
        logger.exception("Could not initialise clipboard storage")
        QMessageBox.critical(
            None,
            APP_NAME,
            "ClipNest could not open its clipboard database.\n\n"
            f"{exc}",
        )
        return 1
    logger.info(
        "Clipboard storage ready at %s (encrypted=%s)",
        repository.database_path,
        repository.protector.is_encrypted,
    )

    icon = load_app_icon()
    if icon is None:
        report_missing_icon()
    else:
        app.setWindowIcon(icon)

    # The pause state is resolved before any window exists, so the button, the
    # banner, the tray label and the service all start on the same value.
    start_paused, pause_state_unreadable = read_startup_pause(preferences)

    clipboard_service = create_clipboard_service(
        app.clipboard(),
        repository,
        sensitive_enabled=preferences.sensitive_detection_enabled(),
        paused=start_paused,
    )
    window = create_main_window(
        repository, clipboard_service, window_icon=icon, preferences=preferences
    )

    tray = create_tray_icon(icon)
    if tray is not None:
        tray_watchdog = wire_tray(tray, window, clipboard_service, app)
        tray_watchdog.start()
    else:
        logger.info("Running without a tray; closing the window quits ClipNest")

    window.show()

    clipboard_service.start()
    app.aboutToQuit.connect(clipboard_service.stop)
    app.aboutToQuit.connect(_log_shutdown)
    logger.info("Clipboard monitoring started (paused=%s)", start_paused)

    if pause_state_unreadable:
        window.explain_pause_state_unreadable()
    window.announce_monitoring_once()

    return app.exec()


def _log_shutdown() -> None:
    """Record a normal shutdown, so a support log can tell it from a crash."""
    logger.info("ClipNest shutting down")


if __name__ == "__main__":
    raise SystemExit(main())
