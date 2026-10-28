"""Scrollable history of snippet cards with selection and empty states.

Presentation only: the view is handed :class:`ClipboardEntry` values and emits
user intent (activate, pin, delete, clear search) as ids. It never imports
``sqlite3`` and never reads the clipboard.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from clipnest.core.classifier import TextKind, classify_text
from clipnest.core.storage import ClipboardEntry
from clipnest.ui.snippet_card import SnippetCard
from clipnest.ui.state_panel import SkeletonList, StatePanel

EMPTY_STATES: dict[str, tuple[str, str, str]] = {
    "all": (
        "inbox",
        "No clipboard history yet",
        "Copy any text in Windows and it appears here instantly.",
    ),
    "pinned": (
        "pinned",
        "No pinned snippets",
        "Pin the snippets you reuse most and they stay at the top of the list.",
    ),
    "text": (
        "text",
        "No text snippets",
        "Plain text you copy is collected under Text.",
    ),
    "link": (
        "link",
        "No links yet",
        "Copy a URL or a bare domain and it is filed under Links.",
    ),
    "code": (
        "code",
        "No code snippets",
        "Copy a snippet of code and it is filed under Code.",
    ),
    "search": (
        "search",
        "No matching snippets",
        "Try a shorter word, or clear the search to see everything again.",
    ),
}


class HistoryView(QWidget):
    """Card list with selection, keyboard navigation, and state placeholders."""

    entry_activated = Signal(int)
    pin_toggled = Signal(int, bool)
    selection_changed = Signal(object)
    delete_requested = Signal(int)
    clear_search_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[SnippetCard] = []
        self._entries: dict[int, ClipboardEntry] = {}
        self._kinds: dict[int, TextKind] = {}
        self._trimmed_ids: set[int] = set()
        self._selected_id: int | None = None

        self._stack = QStackedWidget(self)

        # Page 0: cards
        self.scroll_area = QScrollArea(self._stack)
        self.scroll_area.setObjectName("HistoryScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._container = QWidget()
        self._container.setObjectName("HistoryContainer")
        self._rows_layout = QVBoxLayout(self._container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)
        self._rows_layout.addStretch(1)
        self.scroll_area.setWidget(self._container)

        # Page 1: empty / error state
        self.state_panel = StatePanel("inbox", "", "", parent=self._stack)
        self.state_panel.action_clicked.connect(self.clear_search_requested)

        # Page 2: skeleton
        self.skeleton = SkeletonList(parent=self._stack)

        self._stack.addWidget(self.scroll_area)
        self._stack.addWidget(self.state_panel)
        self._stack.addWidget(self.skeleton)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._stack)

    # ------------------------------------------------------------------ API

    def count(self) -> int:
        """Number of cards currently displayed."""
        return len(self.rows)

    def set_entries(
        self,
        entries: list[ClipboardEntry],
        empty_kind: str = "all",
        query: str = "",
        trimmed_ids: set[int] | None = None,
    ) -> None:
        """Rebuild the cards from ``entries``, preserving selection when possible."""
        self._clear_rows()
        self._entries = {entry.id: entry for entry in entries}
        self._trimmed_ids = set(trimmed_ids or ())

        for entry in entries:
            kind = classify_text(entry.text)
            self._kinds[entry.id] = kind
            card = SnippetCard(
                entry,
                kind,
                selected=entry.id == self._selected_id,
                trimmed=entry.id in self._trimmed_ids,
                parent=self._container,
            )
            card.clicked.connect(self._on_card_clicked)
            card.pin_toggled.connect(self.pin_toggled)
            card.installEventFilter(self)
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, card)
            self.rows.append(card)

        if not entries:
            self._selected_id = None
            self._show_empty_state(empty_kind, query)
            self.selection_changed.emit(None)
            return

        self._stack.setCurrentWidget(self.scroll_area)
        if self._selected_id not in self._entries:
            self._apply_selection(entries[0].id)
        else:
            self._apply_selection(self._selected_id, emit=False)

    def show_loading(self) -> None:
        """Show skeleton cards while a slow load is in flight."""
        self._stack.setCurrentWidget(self.skeleton)

    def show_error(self, message: str) -> None:
        """Replace the list with a recoverable error state.

        The cards go too: after a failed read they describe a snapshot that
        can no longer be confirmed, so keeping them (even hidden) would let
        ``count``, the selection, and the detail panel keep reporting stale
        history as if it were current.
        """
        self._clear_rows()
        self._selected_id = None
        self.state_panel.configure("alert", "Could not load history", message)
        self._stack.setCurrentWidget(self.state_panel)
        # Re-apply the wrapped description height, as the empty state does.
        panel_layout = self.state_panel.layout()
        if panel_layout is not None:
            panel_layout.activate()

    def is_showing_loading(self) -> bool:
        return self._stack.currentWidget() is self.skeleton

    def is_showing_state(self) -> bool:
        return self._stack.currentWidget() is self.state_panel

    @property
    def selected_id(self) -> int | None:
        return self._selected_id

    @property
    def selected_entry(self) -> ClipboardEntry | None:
        if self._selected_id is None:
            return None
        return self._entries.get(self._selected_id)

    def selected_kind(self) -> TextKind | None:
        if self._selected_id is None:
            return None
        return self._kinds.get(self._selected_id)

    def select(self, entry_id: int) -> None:
        """Select ``entry_id`` if it is currently displayed."""
        if entry_id in self._entries:
            self._apply_selection(entry_id)

    def clear_selection(self) -> None:
        self._selected_id = None
        for card in self.rows:
            card.set_selected(False)
        self.selection_changed.emit(None)

    def selected_card(self) -> SnippetCard | None:
        for card in self.rows:
            if card.entry_id == self._selected_id:
                return card
        return None

    def focus_selected_card(self) -> None:
        card = self.selected_card()
        if card is not None:
            card.setFocus(Qt.FocusReason.OtherFocusReason)

    def refresh_theme(self) -> None:
        """Re-tint the placeholder icon; cards are rebuilt by the window."""
        self.state_panel.refresh_theme()

    # -------------------------------------------------------------- keyboard

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.KeyPress and isinstance(watched, SnippetCard):
            key = event.key()
            if key == Qt.Key.Key_Down:
                self._move_selection(1)
                return True
            if key == Qt.Key.Key_Up:
                self._move_selection(-1)
                return True
            if key == Qt.Key.Key_Delete and self._selected_id is not None:
                self.delete_requested.emit(self._selected_id)
                return True
        return super().eventFilter(watched, event)

    def _move_selection(self, delta: int) -> None:
        if not self.rows:
            return
        ids = [card.entry_id for card in self.rows]
        try:
            index = ids.index(self._selected_id) if self._selected_id else 0
        except ValueError:
            index = 0
        new_index = max(0, min(len(ids) - 1, index + delta))
        self._apply_selection(ids[new_index])
        self.focus_selected_card()
        card = self.selected_card()
        if card is not None:
            self.scroll_area.ensureWidgetVisible(card)

    # ------------------------------------------------------------- internals

    def _on_card_clicked(self, entry_id: int) -> None:
        self._apply_selection(entry_id, emit=False)
        self.entry_activated.emit(entry_id)

    def _apply_selection(self, entry_id: int, emit: bool = True) -> None:
        self._selected_id = entry_id
        for card in self.rows:
            card.set_selected(card.entry_id == entry_id)
        if emit:
            self.selection_changed.emit(self._entries.get(entry_id))

    def _show_empty_state(self, empty_kind: str, query: str) -> None:
        if query:
            _icon, _title, description = EMPTY_STATES["search"]
            self.state_panel.configure(
                "search",
                f'No matches for "{query}"',
                description,
                action_text="Clear search",
            )
        else:
            icon_name, title, description = EMPTY_STATES.get(
                empty_kind, EMPTY_STATES["all"]
            )
            self.state_panel.configure(icon_name, title, description)
        self._stack.setCurrentWidget(self.state_panel)
        # The panel is reconfigured in place, so ask its layout to re-apply the
        # wrapped description height before the next paint.
        panel_layout = self.state_panel.layout()
        if panel_layout is not None:
            panel_layout.activate()

    def _clear_rows(self) -> None:
        for card in self.rows:
            self._rows_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self.rows.clear()
        self._entries = {}
        self._kinds = {}
