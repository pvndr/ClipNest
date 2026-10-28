"""Inline notification bar for transient feedback and the paused banner.

One widget type covers both: a transient toast-style message (copy, pin,
delete, errors) and a persistent banner (monitoring paused) that stays until
the state changes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QWidget,
)

from clipnest.ui import icons
from clipnest.ui.theme import theme

SEVERITY_ICONS = {
    "info": "about",
    "success": "check",
    "warning": "alert",
    "error": "alert",
}


class NotificationBar(QFrame):
    """A single-line message with optional action and dismiss button."""

    action_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NotificationBar")
        self.setProperty("severity", "info")
        self._last: tuple[str, str, str | None, str | None] = ("", "info", None, None)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

        self._icon = QLabel(self)
        self._icon.setFixedSize(16, 16)

        self.message_label = QLabel("", self)
        self.message_label.setObjectName("NotificationText")
        self.message_label.setWordWrap(True)

        self.action_button = QPushButton("", self)
        self.action_button.setObjectName("GhostButton")
        self.action_button.setCursor(self.cursor())
        self.action_button.clicked.connect(self.action_clicked)
        self.action_button.hide()

        self.close_button = QToolButton(self)
        self.close_button.setObjectName("CardAction")
        self.close_button.setIcon(icons.icon("close", theme().text_muted, 14))
        self.close_button.setAccessibleName("Dismiss notification")
        self.close_button.setToolTip("Dismiss")
        self.close_button.clicked.connect(self.dismiss)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 8, 7)
        layout.setSpacing(8)
        layout.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.message_label, stretch=1)
        layout.addWidget(self.action_button)
        layout.addWidget(
            self.close_button, alignment=Qt.AlignmentFlag.AlignVCenter
        )

        self.hide()

    # ------------------------------------------------------------------ API

    def show_message(
        self,
        message: str,
        severity: str = "info",
        timeout_ms: int | None = 4000,
        action_text: str | None = None,
        icon_name: str | None = None,
    ) -> None:
        """Display ``message``; ``timeout_ms=None`` keeps it until dismissed."""
        self._configure(message, severity, action_text, icon_name)
        self._timer.stop()
        if timeout_ms is not None:
            self._timer.start(timeout_ms)

    def dismiss(self) -> None:
        """Hide the bar and stop any pending auto-dismiss."""
        self._timer.stop()
        self.hide()

    @property
    def message(self) -> str:
        return self.message_label.text()

    @property
    def severity(self) -> str:
        return str(self.property("severity"))

    def refresh_theme(self) -> None:
        """Re-tint the close and severity icons after a theme change."""
        self.close_button.setIcon(icons.icon("close", theme().text_muted, 14))
        if self.isVisible():
            self._configure(*self._last)

    # ------------------------------------------------------------ internals

    def _configure(
        self,
        message: str,
        severity: str,
        action_text: str | None,
        icon_name: str | None = None,
    ) -> None:
        self._last = (message, severity, action_text, icon_name)
        self.message_label.setText(message)
        self.setProperty("severity", severity)

        color = {
            "success": theme().success,
            "warning": theme().warning,
            "error": theme().danger,
            "info": theme().accent,
        }.get(severity, theme().accent)
        self._icon.setPixmap(
            icons.pixmap(
                icon_name or SEVERITY_ICONS.get(severity, "about"), color, 16
            )
        )

        self.action_button.setText(action_text or "")
        self.action_button.setVisible(bool(action_text))

        for widget in (self, self.message_label, self._icon):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.show()
