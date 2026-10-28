"""Selected-snippet preview panel.

Shows the full content and metadata for the selected entry plus its actions.
All three actions only emit ids; the window performs the work through the
repository and clipboard service, so no business logic lives here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from clipnest.core.classifier import TextKind
from clipnest.core.storage import ClipboardEntry
from clipnest.ui import icons
from clipnest.ui.snippet_card import KIND_ICONS, relative_time
from clipnest.ui.state_panel import StatePanel
from clipnest.ui.theme import theme

PANEL_WIDTH = 320


class DetailPanel(QFrame):
    """Right-hand preview for the selected snippet."""

    copy_requested = Signal(int)
    pin_toggled = Signal(int, bool)
    delete_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DetailPanel")
        self.setMinimumWidth(PANEL_WIDTH)
        self.setMaximumWidth(PANEL_WIDTH + 40)
        self._entry: ClipboardEntry | None = None
        self._kind = TextKind.TEXT
        self._trimmed = False

        self._stack = QStackedWidget(self)
        self._placeholder = StatePanel(
            "copy",
            "Nothing selected",
            "Pick a snippet from the history to preview it here.",
            parent=self._stack,
        )
        self._details = self._build_details()
        self._stack.addWidget(self._placeholder)
        self._stack.addWidget(self._details)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)
        layout.addWidget(self._stack)

        self.set_entry(None)

    # ------------------------------------------------------------------ API

    def set_entry(
        self,
        entry: ClipboardEntry | None,
        kind: TextKind | None = None,
        trimmed: bool = False,
    ) -> None:
        """Show ``entry``, or the placeholder when it is ``None``."""
        self._entry = entry
        if entry is None:
            self._trimmed = False
            self._stack.setCurrentWidget(self._placeholder)
            return

        self._kind = kind or TextKind.TEXT
        self._trimmed = bool(trimmed)
        self._stack.setCurrentWidget(self._details)

        self.kind_icon.setPixmap(
            icons.pixmap(KIND_ICONS[self._kind], theme().text_muted, 16)
        )
        self.kind_label.setText(self._kind.value.capitalize())
        self.time_label.setText(relative_time(entry.created_at))
        self.chars_label.setText(f"{len(entry.text):,}")
        self.lines_label.setText(f"{len(entry.text.splitlines()) or 1:,}")

        self.content.setPlainText(entry.text)
        self._apply_content_font()

        self.trimmed_note.setVisible(trimmed)
        if trimmed:
            limit = len(entry.text)
            self.trimmed_note.setText(
                f"Trimmed to {limit:,} characters when captured. "
                "The original copy was longer."
            )

        self.pin_button.setText("Unpin" if entry.pinned else "Pin")
        self.pin_button.setIcon(
            icons.icon(
                "pinned",
                theme().text if entry.pinned else theme().text_muted,
                16,
                filled=entry.pinned,
            )
        )

    @property
    def entry_id(self) -> int | None:
        return self._entry.id if self._entry else None

    def refresh_theme(self) -> None:
        """Re-tint the panel icons after the application theme changed."""
        self._placeholder.refresh_theme()
        self.set_entry(self._entry, self._kind, self._trimmed)

    # ------------------------------------------------------------- internals

    def _build_details(self) -> QWidget:
        container = QWidget(self._stack)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QWidget(container)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        self.kind_icon = QLabel(header)
        self.kind_icon.setFixedSize(16, 16)

        self.kind_label = QLabel("Text", header)
        self.kind_label.setObjectName("DetailTitle")

        self.time_label = QLabel("", header)
        self.time_label.setObjectName("DetailLabel")

        header_layout.addWidget(self.kind_icon)
        header_layout.addWidget(self.kind_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.time_label)

        self.content = QPlainTextEdit(container)
        self.content.setObjectName("DetailContent")
        self.content.setReadOnly(True)
        self.content.setMinimumHeight(160)
        self.content.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.content.setAccessibleName("Snippet content")

        self.trimmed_note = QLabel("", container)
        self.trimmed_note.setObjectName("DetailNote")
        self.trimmed_note.setWordWrap(True)
        self.trimmed_note.setVisible(False)

        meta = QWidget(container)
        meta_layout = QHBoxLayout(meta)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(18)

        self.chars_label = self._add_meta(meta_layout, "Characters")
        self.lines_label = self._add_meta(meta_layout, "Lines")
        meta_layout.addStretch(1)

        divider = QFrame(container)
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)

        self.copy_button = QPushButton("Copy again", container)
        self.copy_button.setObjectName("PrimaryButton")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self._emit_copy)

        actions = QWidget(container)
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        self.pin_button = QPushButton("Pin", actions)
        self.pin_button.setObjectName("SecondaryButton")
        self.pin_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_button.clicked.connect(self._emit_pin)

        self.delete_button = QPushButton("Delete", actions)
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.clicked.connect(self._emit_delete)

        actions_layout.addWidget(self.pin_button)
        actions_layout.addWidget(self.delete_button)
        actions_layout.addStretch(1)

        layout.addWidget(header)
        layout.addWidget(self.content, stretch=1)
        layout.addWidget(self.trimmed_note)
        layout.addWidget(meta)
        layout.addWidget(divider)
        layout.addWidget(self.copy_button)
        layout.addWidget(actions)
        return container

    def _add_meta(self, parent_layout: QHBoxLayout, caption: str) -> QLabel:
        box = QWidget()
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(1)

        caption_label = QLabel(caption, box)
        caption_label.setObjectName("DetailLabel")

        value_label = QLabel("-", box)
        value_label.setObjectName("DetailValue")

        box_layout.addWidget(caption_label)
        box_layout.addWidget(value_label)
        parent_layout.addWidget(box)
        return value_label

    def _apply_content_font(self) -> None:
        # QPlainTextEdit defaults to a fixed font; prose should use the UI font.
        role = (
            QFontDatabase.SystemFont.FixedFont
            if self._kind is TextKind.CODE
            else QFontDatabase.SystemFont.GeneralFont
        )
        font = QFontDatabase.systemFont(role)
        font.setPointSize(9)
        self.content.setFont(font)

    def _emit_copy(self) -> None:
        if self._entry is not None:
            self.copy_requested.emit(self._entry.id)

    def _emit_pin(self) -> None:
        if self._entry is not None:
            self.pin_toggled.emit(self._entry.id, not self._entry.pinned)

    def _emit_delete(self) -> None:
        if self._entry is not None:
            self.delete_requested.emit(self._entry.id)
