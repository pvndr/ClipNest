"""Sidebar navigation.

Categories are a filter over the same history list — selecting one never opens
another window. Settings and About are informational pages handled by the
window; this widget only reports which item is active.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from clipnest.ui import icons
from clipnest.ui.theme import theme

CATEGORY_ITEMS = (
    ("all", "All", "all"),
    ("pinned", "Pinned", "pinned"),
    ("text", "Text", "text"),
    ("link", "Links", "link"),
    ("code", "Code", "code"),
)

PAGE_ITEMS = (
    ("settings", "Settings", "settings"),
    ("about", "About", "about"),
)

EXPANDED_WIDTH = 212
COMPACT_WIDTH = 64


class NavButton(QToolButton):
    """Icon + label navigation entry with a checked state."""

    def __init__(
        self, key: str, label: str, icon_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._icon_name = icon_name

        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText(label)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setAccessibleName(label)
        self.setToolTip(label)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.toggled.connect(self.refresh_theme)
        self.refresh_theme()

    def set_compact(self, compact: bool) -> None:
        """Hide the label, keeping the tooltip and accessible name."""
        self.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
            if compact
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )

    def refresh_theme(self) -> None:
        """Re-render the icon for the active theme and checked state."""
        color = theme().accent if self.isChecked() else theme().text_muted
        self.setIcon(icons.icon(self._icon_name, color, 18))


class Sidebar(QWidget):
    """Compact left navigation with a section for filters and one for pages."""

    category_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(EXPANDED_WIDTH)

        self._buttons: dict[str, NavButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 14)
        layout.setSpacing(4)

        layout.addWidget(self._build_brand())
        layout.addSpacing(12)

        self.section_label = QLabel("Library", self)
        self.section_label.setObjectName("SectionLabel")
        layout.addWidget(self.section_label)

        for key, label, icon_name in CATEGORY_ITEMS:
            layout.addWidget(self._add_button(key, label, icon_name))

        layout.addStretch(1)

        divider = QFrame(self)
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(6)

        for key, label, icon_name in PAGE_ITEMS:
            layout.addWidget(self._add_button(key, label, icon_name))

        self._buttons["all"].setChecked(True)

    # ------------------------------------------------------------------ API

    @property
    def current_category(self) -> str:
        """Key of the active navigation item."""
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return "all"

    def set_current(self, key: str) -> None:
        """Activate ``key`` without emitting a change signal."""
        button = self._buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def buttons(self) -> dict[str, NavButton]:
        """Navigation buttons by key (used by tests and the window)."""
        return dict(self._buttons)

    def set_compact(self, compact: bool) -> None:
        """Collapse to icons only when horizontal space is tight."""
        self.setFixedWidth(COMPACT_WIDTH if compact else EXPANDED_WIDTH)
        self.brand_label.setVisible(not compact)
        self.section_label.setVisible(not compact)
        for button in self._buttons.values():
            button.set_compact(compact)

    def refresh_theme(self) -> None:
        """Re-tint every navigation icon after a theme change."""
        for button in self._buttons.values():
            button.refresh_theme()

    # ------------------------------------------------------------- internals

    def _build_brand(self) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(9)

        mark = QFrame(row)
        mark.setObjectName("BrandMark")
        mark.setFixedSize(18, 18)

        self.brand_label = QLabel("ClipNest", row)
        self.brand_label.setObjectName("Brand")

        layout.addWidget(mark)
        layout.addWidget(self.brand_label)
        layout.addStretch(1)
        return row

    def _add_button(self, key: str, label: str, icon_name: str) -> NavButton:
        button = NavButton(key, label, icon_name, self)
        self._group.addButton(button)
        self._buttons[key] = button
        button.toggled.connect(lambda checked, k=key: self._on_toggled(k, checked))
        return button

    def _on_toggled(self, key: str, checked: bool) -> None:
        if checked:
            self.category_changed.emit(key)
