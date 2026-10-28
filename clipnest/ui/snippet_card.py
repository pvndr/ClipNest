"""A single history snippet card.

Presentation only: it renders one :class:`ClipboardEntry` and emits user
intent as ids. It never reads the clipboard or the database.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from clipnest.core.classifier import TextKind
from clipnest.core.storage import ClipboardEntry
from clipnest.ui import icons
from clipnest.ui.theme import theme

PREVIEW_CHARS = 220
TOOLTIP_CHARS = 500
PREVIEW_MAX_HEIGHT = 38
CODE_PREVIEW_LINES = 2
MAX_TOKEN_CHARS = 64

KIND_ICONS = {
    TextKind.TEXT: "text",
    TextKind.LINK: "link",
    TextKind.CODE: "code",
}


class SnippetCard(QFrame):
    """Card showing a content-type icon, preview, metadata and a pin toggle."""

    clicked = Signal(int)
    pin_toggled = Signal(int, bool)

    def __init__(
        self,
        entry: ClipboardEntry,
        kind: TextKind,
        selected: bool = False,
        trimmed: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entry_id = entry.id
        self.kind = kind

        self.setObjectName("SnippetCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("selected", "true" if selected else "false")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(_summarise(entry.text, TOOLTIP_CHARS))
        self.setAccessibleName(
            f"{kind.value.capitalize()} snippet: {_summarise(entry.text, 60)}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(12)

        self.kind_icon = QLabel(self)
        self.kind_icon.setFixedSize(18, 18)
        self.kind_icon.setPixmap(
            icons.pixmap(KIND_ICONS[kind], theme().text_muted, 18)
        )

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(4)

        self.preview_label = QLabel(_preview_text(entry.text, kind), self)
        self.preview_label.setObjectName("CardPreview")
        self.preview_label.setWordWrap(True)
        self.preview_label.setMaximumHeight(PREVIEW_MAX_HEIGHT)
        # Long unbroken strings must never widen the card: without this the
        # label's size hint inflates the scroll area and clips every card.
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.preview_label.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )

        meta_row = QWidget(self)
        meta_layout = QHBoxLayout(meta_row)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(8)

        self.meta_label = QLabel(_meta_text(entry), meta_row)
        self.meta_label.setObjectName("CardMeta")
        meta_layout.addWidget(self.meta_label)

        self.trimmed_badge = QLabel("Trimmed", meta_row)
        self.trimmed_badge.setObjectName("CardBadge")
        self.trimmed_badge.setToolTip(
            "This snippet reached the maximum stored length and was shortened."
        )
        self.trimmed_badge.setVisible(trimmed)
        meta_layout.addWidget(self.trimmed_badge)

        if entry.pinned:
            self.pinned_badge = QLabel("Pinned", meta_row)
            self.pinned_badge.setObjectName("CardBadge")
            meta_layout.addWidget(self.pinned_badge)
        else:
            self.pinned_badge = None

        meta_layout.addStretch(1)

        text_column.addWidget(self.preview_label)
        text_column.addWidget(meta_row)

        self.pin_button = QToolButton(self)
        self.pin_button.setObjectName("CardAction")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(entry.pinned)
        self.pin_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_button.setToolTip(
            "Unpin this snippet" if entry.pinned else "Pin this snippet"
        )
        self.pin_button.setAccessibleName(
            "Unpin snippet" if entry.pinned else "Pin snippet"
        )
        self._refresh_pin_icon()
        self.pin_button.toggled.connect(self._on_pin_toggled)

        layout.addWidget(self.kind_icon, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text_column, stretch=1)
        layout.addWidget(self.pin_button, alignment=Qt.AlignmentFlag.AlignTop)

    # ------------------------------------------------------------------ API

    def set_selected(self, selected: bool) -> None:
        """Apply the selected visual state."""
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def is_selected(self) -> bool:
        return self.property("selected") == "true"

    # ------------------------------------------------------------- internals

    def _on_pin_toggled(self, pinned: bool) -> None:
        self.pin_button.setToolTip(
            "Unpin this snippet" if pinned else "Pin this snippet"
        )
        self.pin_button.setAccessibleName(
            "Unpin snippet" if pinned else "Pin snippet"
        )
        self._refresh_pin_icon()
        self.pin_toggled.emit(self.entry_id, pinned)

    def _refresh_pin_icon(self) -> None:
        color = theme().accent if self.pin_button.isChecked() else theme().text_muted
        self.pin_button.setIcon(
            icons.icon("pinned", color, 16, filled=self.pin_button.isChecked())
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.entry_id)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.entry_id)
            event.accept()
            return
        super().keyPressEvent(event)


def _summarise(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "..."


def _preview_text(text: str, kind: TextKind, limit: int = PREVIEW_CHARS) -> str:
    """Shorten ``text`` for a card, keeping code line breaks readable."""
    if kind is TextKind.CODE:
        lines = [line.rstrip() for line in text.strip().splitlines()]
        head = "\n".join(_cap_token(line) for line in lines[:CODE_PREVIEW_LINES])
        if len(lines) > CODE_PREVIEW_LINES:
            head += "\n..."
        if len(head) <= limit:
            return head
        return head[:limit].rstrip() + "..."
    collapsed = " ".join(_cap_token(word) for word in text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "..."


def _cap_token(token: str) -> str:
    """Shorten one unbroken token so a blob cannot fill the whole card."""
    if len(token) <= MAX_TOKEN_CHARS:
        return token
    return token[: MAX_TOKEN_CHARS - 3] + "..."


def _meta_text(entry: ClipboardEntry) -> str:
    lines = len(entry.text.splitlines()) or 1
    line_label = "line" if lines == 1 else "lines"
    return (
        f"{relative_time(entry.created_at)} - {len(entry.text):,} chars - "
        f"{lines:,} {line_label}"
    )


def relative_time(created_at: datetime) -> str:
    """Render a stored timestamp as a short relative label."""
    moment = created_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - moment).total_seconds()

    if seconds < 45:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86_400:
        return f"{int(seconds // 3600)} h ago"
    if seconds < 604_800:
        return f"{int(seconds // 86_400)} d ago"
    return moment.astimezone().strftime("%d %b %Y")
