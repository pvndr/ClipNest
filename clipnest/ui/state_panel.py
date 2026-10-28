"""Empty, loading and error state widgets.

Shared by the history list so every "nothing here" case looks the same.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from clipnest.ui import icons
from clipnest.ui.theme import theme

DESCRIPTION_MAX_WIDTH = 340
DESCRIPTION_MIN_WIDTH = 200


class StatePanel(QWidget):
    """Centred icon, title, description, and an optional action button."""

    action_clicked = Signal()

    def __init__(
        self,
        icon_name: str,
        title: str,
        description: str,
        action_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_label = QLabel(self)
        self._icon_label.setObjectName("StateIcon")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_box = QFrame(self)
        icon_box.setObjectName("StateIconBox")
        icon_box.setFixedSize(48, 48)
        icon_layout = QVBoxLayout(icon_box)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.addWidget(self._icon_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("StateTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.description_label = QLabel(description, self)
        self.description_label.setObjectName("StateDescription")
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label.setWordWrap(True)
        self.description_label.setMaximumWidth(DESCRIPTION_MAX_WIDTH)
        self.description_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )

        self.action_button = QPushButton(action_text or "", self)
        self.action_button.setObjectName("SecondaryButton")
        self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_button.setVisible(bool(action_text))
        self.action_button.clicked.connect(self.action_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(10)
        layout.addStretch(1)
        layout.addWidget(icon_box, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.title_label)
        layout.addWidget(
            self.description_label, alignment=Qt.AlignmentFlag.AlignHCenter
        )
        layout.addWidget(
            self.action_button, alignment=Qt.AlignmentFlag.AlignHCenter
        )
        layout.addStretch(1)

        self._refresh_icon()
        self._fit_description()

    def configure(
        self,
        icon_name: str,
        title: str,
        description: str,
        action_text: str | None = None,
    ) -> None:
        """Reuse this panel for a different state."""
        self._icon_name = icon_name
        self.title_label.setText(title)
        self.description_label.setText(description)
        self.action_button.setText(action_text or "")
        self.action_button.setVisible(bool(action_text))
        self._refresh_icon()
        self._fit_description()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._fit_description()

    def refresh_theme(self) -> None:
        """Re-tint the state icon after the application theme changed."""
        self._refresh_icon()

    def _fit_description(self) -> None:
        """Pin the wrap width so the wrapped height is computed consistently.

        ``QLabel`` derives its height-for-width from whatever width it last
        had, so a centred label capped with ``maximumWidth`` can be given a
        one-line height while painting two lines. Fixing the width keeps the
        hint and the geometry in agreement.
        """
        available = max(DESCRIPTION_MIN_WIDTH, self.width() - 48)
        width = min(DESCRIPTION_MAX_WIDTH, available)
        if self.description_label.width() != width:
            self.description_label.setFixedWidth(width)
        needed = self.description_label.heightForWidth(width)
        if needed > 0 and self.description_label.minimumHeight() != needed:
            self.description_label.setMinimumHeight(needed)

    def _refresh_icon(self) -> None:
        self._icon_label.setPixmap(
            icons.pixmap(self._icon_name, theme().text_muted, 22)
        )


class SkeletonList(QWidget):
    """Static placeholder cards used while a slow load is in flight.

    Deliberately not animated: the skeleton only appears when a load actually
    exceeds the responsiveness threshold, and motion would draw attention to a
    state the user should barely notice.
    """

    def __init__(self, rows: int = 4, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.bars: list[QLabel] = []
        for index in range(rows):
            bar = QLabel(self)
            bar.setObjectName("SkeletonBar")
            bar.setFixedHeight(62)
            bar.setProperty("row", index)
            layout.addWidget(bar)
            self.bars.append(bar)
        layout.addStretch(1)
