"""System tray icon and its context menu.

The tray is deliberately thin: it owns no repository and no clipboard state.
Every menu entry emits a signal and the composition root (:mod:`clipnest.app`)
decides what happens, so the tray can be driven from tests without a real
Windows shell.

Menu:
  Show ClipNest            -> show_requested
  Pause/Resume Monitoring  -> pause_toggled   (label follows the paused state)
  Clear Unpinned History   -> clear_requested
  Quit                     -> quit_requested
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

logger = logging.getLogger(__name__)

SHOW_TEXT = "Show ClipNest"
PAUSE_TEXT = "Pause Monitoring"
RESUME_TEXT = "Resume Monitoring"
CLEAR_TEXT = "Clear Unpinned History"
QUIT_TEXT = "Quit"

TOOLTIP_ACTIVE = "ClipNest - monitoring clipboard"
TOOLTIP_PAUSED = "ClipNest - monitoring paused"

HIDDEN_TITLE = "ClipNest is still running"
HIDDEN_BODY = (
    "Clipboard monitoring continues in the background. "
    "Open the tray menu to restore the window or quit."
)
HIDDEN_TIMEOUT_MS = 4000


class TrayIcon(QSystemTrayIcon):
    """The ClipNest tray icon plus its Show / Pause / Clear / Quit menu."""

    show_requested = Signal()
    pause_toggled = Signal()
    clear_requested = Signal()
    quit_requested = Signal()

    def __init__(
        self,
        icon: QIcon | None = None,
        parent: QObject | None = None,
    ) -> None:
        # No icon means no valid asset was supplied; the tray still works and
        # requests a real icon from the shell rather than inventing artwork.
        super().__init__(icon if icon is not None else QIcon(), parent)
        self._paused = False
        self._hint_shown = False

        # QMenu needs a QWidget parent, so the tray keeps the only reference.
        self.menu = QMenu()
        self.menu.setObjectName("TrayMenu")

        self.show_action = QAction(SHOW_TEXT, self)
        self.pause_action = QAction(PAUSE_TEXT, self)
        self.clear_action = QAction(CLEAR_TEXT, self)
        self.quit_action = QAction(QUIT_TEXT, self)
        self.show_action.setObjectName("TrayShowAction")
        self.pause_action.setObjectName("TrayPauseAction")
        self.clear_action.setObjectName("TrayClearAction")
        self.quit_action.setObjectName("TrayQuitAction")

        self.menu.addAction(self.show_action)
        self.menu.addAction(self.pause_action)
        self.menu.addSeparator()
        self.menu.addAction(self.clear_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.setContextMenu(self.menu)

        self.show_action.triggered.connect(self.show_requested)
        self.pause_action.triggered.connect(self.pause_toggled)
        self.clear_action.triggered.connect(self.clear_requested)
        self.quit_action.triggered.connect(self.quit_requested)
        self.activated.connect(self._on_activated)

        self.setToolTip(TOOLTIP_ACTIVE)

    # ------------------------------------------------------------ pause state

    @property
    def paused(self) -> bool:
        """Whether the tray currently reports monitoring as paused."""
        return self._paused

    def set_paused(self, paused: bool) -> None:
        """Mirror the clipboard service state in the menu label and tooltip."""
        self._paused = bool(paused)
        self.pause_action.setText(RESUME_TEXT if self._paused else PAUSE_TEXT)
        self.setToolTip(TOOLTIP_PAUSED if self._paused else TOOLTIP_ACTIVE)

    # --------------------------------------------------------------- recovery

    def recover(self) -> bool:
        """Re-register the icon with the shell and report whether it is back.

        Qt's Windows backend already re-adds the icon itself when Explorer
        broadcasts its taskbar-recreated message; calling this on a healthy
        tray is still safe because ``show()`` updates the one icon this object
        owns instead of adding a second one. Returns ``False`` while the
        platform reports no usable tray at all.
        """
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        self.show()
        return self.isVisible()

    # --------------------------------------------------------------- feedback

    def notify_hidden_once(self) -> None:
        """Explain the first hide-to-tray once, when the shell can show messages."""
        if self._hint_shown:
            return
        self._hint_shown = True
        if not self.supportsMessages():
            logger.debug("Tray messages unsupported; skipping the hint")
            return
        self.showMessage(
            HIDDEN_TITLE,
            HIDDEN_BODY,
            QSystemTrayIcon.MessageIcon.Information,
            HIDDEN_TIMEOUT_MS,
        )

    # -------------------------------------------------------------- internals

    def _on_activated(
        self, reason: QSystemTrayIcon.ActivationReason
    ) -> None:
        # A left click on the tray icon is the fastest way back to the window.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()
