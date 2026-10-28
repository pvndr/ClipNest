"""Main window: sidebar, history content, and snippet preview.

Composition only — every action is delegated to the repository or the
clipboard service. The window owns navigation state, selection, and the
transient notifications that report the outcome of those actions.

Wiring:
  clipboard.entry_captured     -> reload history (repository read)
  history.card clicked         -> copy through the clipboard service
  history/detail pin toggled   -> repository.set_pinned -> reload
  detail delete / Delete key   -> repository.delete -> reload
  sidebar category             -> filter the same list (pinned / text / links / code)
  pause button, banner action  -> clipboard service pause/resume
  settings page                -> theme, retention limit, pause, clear
  close with tray support      -> hide the window, emit hidden_to_tray

The window never imports the tray: the composition root toggles
:meth:`MainWindow.set_hide_on_close` and calls :meth:`show_from_tray`,
:meth:`toggle_monitoring` and :meth:`clear_unpinned_history` from the tray menu.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from clipnest import __version__
from clipnest.core.classifier import TextKind, classify_text
from clipnest.core.clipboard import ClipboardService
from clipnest.core.storage import ClipboardEntry, ClipboardRepository, StorageError
from clipnest.preferences import Preferences, validate_history_limit
from clipnest.ui import icons
from clipnest.ui.detail_panel import DetailPanel
from clipnest.ui.dialogs import confirm_clear_history
from clipnest.ui.history_view import HistoryView
from clipnest.ui.notification import NotificationBar
from clipnest.ui.settings_page import SettingsPage
from clipnest.ui.sidebar import Sidebar
from clipnest.ui.theme import THEMES, apply_theme, theme

logger = logging.getLogger(__name__)

WINDOW_TITLE = "ClipNest"
DEFAULT_SIZE = (1180, 740)
MINIMUM_SIZE = (720, 500)

DETAIL_PANEL_MIN_WIDTH = 1060
COMPACT_SIDEBAR_MAX_WIDTH = 840
SLOW_LOAD_MS = 150.0

HISTORY_PAGES = ("all", "pinned", "text", "link", "code")
INFO_PAGES = ("settings", "about")

PAGE_COPY: dict[str, tuple[str, str]] = {
    "all": ("All snippets", "Everything you copy, most recent first."),
    "pinned": ("Pinned", "Snippets you keep, safe from history trimming."),
    "text": ("Text", "Plain-text snippets collected automatically."),
    "link": ("Links", "URLs and domains you have copied."),
    "code": ("Code", "Code snippets, filed by content type."),
    "settings": ("Settings", "Appearance, history retention and privacy."),
    "about": ("About ClipNest", "A local-only clipboard history for Windows."),
}

CATEGORY_KINDS = {
    "text": TextKind.TEXT,
    "link": TextKind.LINK,
    "code": TextKind.CODE,
}

# One content-free notice per skip reason. Nothing here names the copied text,
# a matched value, or a token prefix.
SKIP_MESSAGES = {
    "marker": (
        "Not saved: the source application excluded this clipboard content "
        "from monitoring."
    ),
    "history": (
        "Not saved: the source application excluded this clipboard content "
        "from the clipboard history."
    ),
    "invalid": (
        "Not saved: the Windows clipboard privacy markers could not be "
        "interpreted, so the content was ignored."
    ),
    "unreadable": (
        "Not saved: the Windows clipboard privacy markers could not be read, "
        "so the content was ignored."
    ),
    "sensitive": "Not saved: content matched a sensitive-data rule.",
}

# Shown once, on the first start that leaves monitoring running. It describes
# what ClipNest does with the clipboard without naming any captured content.
MONITORING_NOTICE = (
    "ClipNest is now monitoring the clipboard. Copied text is stored on this "
    "device only, and Pause stops capture at any time."
)
# Shown when a stored pause value exists but cannot be interpreted.
PAUSE_STATE_UNREADABLE = (
    "Monitoring is paused because the saved pause setting could not be read. "
    "Press Resume to start capturing again."
)


class MainWindow(QMainWindow):
    """The ClipNest main window."""

    hidden_to_tray = Signal()

    def __init__(
        self,
        repository: ClipboardRepository,
        clipboard_service: ClipboardService,
        window_icon: QIcon | None = None,
        parent: QWidget | None = None,
        preferences: Preferences | None = None,
    ) -> None:
        super().__init__(parent)
        self._repository = repository
        self._clipboard = clipboard_service
        self._preferences = preferences
        self._category = "all"
        self._trimmed_ids: set[int] = set()
        self._slow_loads = False
        self._loading_pending = False
        self._hide_on_close = False

        self.setWindowTitle(WINDOW_TITLE)
        self.setObjectName("MainWindow")
        if window_icon is not None:
            self.setWindowIcon(window_icon)
        self.resize(*DEFAULT_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)

        self._build_ui()
        self._connect_signals()
        self._install_shortcuts()
        self._apply_pause_state(self._clipboard.is_paused)
        # The Settings page is built before the service state is known, so it
        # needs the restored pause state too; otherwise it would read
        # "Pause monitoring" until the user opened the page.
        self.settings_page.set_paused(self._clipboard.is_paused)
        self.settings_page.set_encryption(self._repository.protector.is_encrypted)
        self._update_header()
        self._refresh_history()
        self._apply_responsive_layout()
        self._center_on_screen()

    # ------------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("Root")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = Sidebar(root)
        self.detail_panel = DetailPanel(root)

        content = QWidget(root)
        content.setObjectName("ContentSurface")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 22, 24, 16)
        content_layout.setSpacing(14)

        content_layout.addWidget(self._build_header(content))

        self.pause_banner = NotificationBar(content)
        content_layout.addWidget(self.pause_banner)

        self.notification = NotificationBar(content)
        content_layout.addWidget(self.notification)

        self.content_stack = QStackedWidget(content)
        self.history_page = self._build_history_page()
        self.settings_page = SettingsPage(content)
        self.info_page = self._build_info_page()
        self.content_stack.addWidget(self.history_page)
        self.content_stack.addWidget(self.settings_page)
        self.content_stack.addWidget(self.info_page)
        content_layout.addWidget(self.content_stack, stretch=1)

        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(content, stretch=1)
        root_layout.addWidget(self.detail_panel)

        self.setCentralWidget(root)

    def _build_header(self, parent: QWidget) -> QWidget:
        header = QWidget(parent)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        titles = QWidget(header)
        titles_layout = QVBoxLayout(titles)
        titles_layout.setContentsMargins(0, 0, 0, 0)
        titles_layout.setSpacing(3)

        self.page_title = QLabel("All snippets", titles)
        self.page_title.setObjectName("PageTitle")

        self.page_subtitle = QLabel("", titles)
        self.page_subtitle.setObjectName("PageSubtitle")

        titles_layout.addWidget(self.page_title)
        titles_layout.addWidget(self.page_subtitle)

        self.pause_button = QPushButton("Pause", header)
        self.pause_button.setObjectName("SecondaryButton")
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.setAccessibleName("Pause clipboard monitoring")
        layout.addWidget(titles, stretch=1)
        layout.addWidget(self.pause_button, alignment=Qt.AlignmentFlag.AlignTop)
        return header

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.search_input = QLineEdit(page)
        self.search_input.setObjectName("SearchInput")
        self.search_input.setPlaceholderText("Search your clipboard history")
        self.search_input.setClearButtonEnabled(False)
        self.search_input.setAccessibleName("Search clipboard history")
        self.search_icon_action = self.search_input.addAction(
            icons.icon("search", theme().text_faint, 14),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.clear_search_action = self.search_input.addAction(
            icons.icon("close", theme().text_faint, 14),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self.clear_search_action.setToolTip("Clear search (Esc)")
        self.clear_search_action.setVisible(False)
        self.clear_search_action.triggered.connect(self._clear_search)

        self.history_view = HistoryView(page)

        footer = QWidget(page)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(2, 0, 0, 0)
        footer_layout.setSpacing(8)

        self.count_label = QLabel("", footer)
        self.count_label.setObjectName("PageSubtitle")

        self.clear_button = QPushButton("Clear history", footer)
        self.clear_button.setObjectName("SecondaryButton")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setToolTip(
            "Delete every unpinned snippet. Pinned snippets are kept."
        )
        self.clear_button.setEnabled(False)

        footer_layout.addWidget(self.count_label)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.clear_button)

        layout.addWidget(self.search_input)
        layout.addWidget(self.history_view, stretch=1)
        layout.addWidget(footer)
        return page

    def _build_info_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        card = QFrame(page)
        card.setObjectName("Card")
        card.setMaximumWidth(760)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(12)

        self.info_rows: dict[str, QLabel] = {}
        for key, caption in (
            ("primary", ""),
            ("secondary", ""),
            ("tertiary", ""),
            ("quaternary", ""),
        ):
            row = QWidget(card)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(16)

            caption_label = QLabel(caption, row)
            caption_label.setObjectName("DetailLabel")
            caption_label.setFixedWidth(160)

            value_label = QLabel("-", row)
            value_label.setObjectName("DetailValue")
            value_label.setWordWrap(True)

            row_layout.addWidget(caption_label)
            row_layout.addWidget(value_label, stretch=1)
            card_layout.addWidget(row)

            self.info_rows[key] = value_label
            setattr(self, f"_info_caption_{key}", caption_label)

        self.info_note = QLabel("", card)
        self.info_note.setObjectName("DetailNote")
        self.info_note.setWordWrap(True)

        card_layout.addWidget(self.info_note)
        layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)
        return page

    # -------------------------------------------------------------- wiring

    def _connect_signals(self) -> None:
        self._clipboard.entry_captured.connect(self._on_entry_captured)
        self._clipboard.capture_truncated.connect(self._on_capture_truncated)
        self._clipboard.capture_skipped.connect(self._on_capture_skipped)
        self._clipboard.paused_changed.connect(self._on_pause_changed)
        self._clipboard.error_occurred.connect(self._on_service_error)

        self.sidebar.category_changed.connect(self._on_category_changed)

        self.history_view.entry_activated.connect(self._on_entry_activated)
        self.history_view.pin_toggled.connect(self._on_pin_toggled)
        self.history_view.selection_changed.connect(self._on_selection_changed)
        self.history_view.delete_requested.connect(self._on_delete_entry)
        self.history_view.clear_search_requested.connect(self._clear_search)

        self.detail_panel.copy_requested.connect(self._on_entry_activated)
        self.detail_panel.pin_toggled.connect(self._on_pin_toggled)
        self.detail_panel.delete_requested.connect(self._on_delete_entry)

        self.pause_button.clicked.connect(self.toggle_monitoring)
        self.pause_banner.action_clicked.connect(self._clipboard.resume)
        self.clear_button.clicked.connect(self._on_clear_history)
        self.search_input.textChanged.connect(self._on_search_changed)

        self.settings_page.theme_selected.connect(self.apply_theme_mode)
        self.settings_page.history_limit_requested.connect(self.apply_history_limit)
        self.settings_page.retention_requested.connect(self.apply_retention_days)
        self.settings_page.pause_toggled.connect(self.toggle_monitoring)
        self.settings_page.clear_requested.connect(self.clear_unpinned_history)
        self.settings_page.sensitive_toggled.connect(
            self.apply_sensitive_detection
        )

    def _install_shortcuts(self) -> None:
        # Window-scoped shortcuts: they fire once per keypress, regardless of
        # which child widget (including the search field) holds the focus.
        self.shortcuts: dict[str, QShortcut] = {
            "focus_search": QShortcut(QKeySequence("Ctrl+K"), self),
            "escape": QShortcut(QKeySequence(Qt.Key.Key_Escape), self),
        }
        self.shortcuts["focus_search"].activated.connect(self._focus_search)
        self.shortcuts["escape"].activated.connect(self._on_escape)

    # ------------------------------------------------------ tray / lifecycle

    @property
    def hide_on_close(self) -> bool:
        """Whether closing the window hides it instead of quitting."""
        return self._hide_on_close

    def set_hide_on_close(self, enabled: bool) -> None:
        """Enable hide-to-tray, or restore the normal close-to-quit behaviour."""
        self._hide_on_close = bool(enabled)

    def fall_back_from_tray(self) -> None:
        """Give the window a normal exit path when the tray icon is gone.

        The tray is the only place a hidden window can be restored or quit
        from, so losing it would leave ClipNest unreachable. Restoring
        close-to-quit keeps the application usable without a tray. Idempotent:
        the notice is shown once, on the transition.
        """
        if not self._hide_on_close:
            return
        self.set_hide_on_close(False)
        logger.warning("System tray unavailable; closing the window quits again")
        self._notify(
            "The system tray is unavailable, so closing this window will now "
            "quit ClipNest.",
            "warning",
            timeout_ms=None,
        )

    def show_from_tray(self) -> None:
        """Restore, un-minimise, and focus the window."""
        state = self.windowState() & ~Qt.WindowState.WindowMinimized
        self.setWindowState(state | Qt.WindowState.WindowActive)
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_monitoring(self) -> None:
        """Flip clipboard monitoring (shared by the pause button and the tray)."""
        self._clipboard.toggle_paused()

    def announce_monitoring_once(self) -> bool:
        """Explain clipboard monitoring on the first unpaused start only.

        Called by the composition root once the window is visible, so a test
        fixture that only builds a window never gains an unexpected notice.
        A paused start is skipped without recording anything, so the notice
        still appears on the first start that actually captures.
        """
        if self._preferences is None or self._clipboard.is_paused:
            return False
        if self._preferences.monitoring_notice_shown():
            return False
        self._preferences.set_monitoring_notice_shown(True)
        self._notify(MONITORING_NOTICE, "info", timeout_ms=None)
        return True

    def explain_pause_state_unreadable(self) -> None:
        """Say why a start with an unusable saved pause value is paused."""
        self._notify(PAUSE_STATE_UNREADABLE, "warning", timeout_ms=None)

    def clear_unpinned_history(self) -> None:
        """Clear unpinned history from the tray, with the usual confirmation.

        The confirmation dialog and the resulting notice both belong to this
        window, so it is restored first when it was hidden.
        """
        self.show_from_tray()
        self._on_clear_history()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._hide_on_close and self.isVisible():
            # Hiding keeps clipboard monitoring (and this window) alive; the
            # tray menu owns the real exit path.
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()
            logger.debug("Main window hidden to the system tray")
            return
        super().closeEvent(event)

    # -------------------------------------------------------------- actions

    def _refresh_history(self) -> None:
        if self._category in INFO_PAGES:
            return
        if self._slow_loads and not self._loading_pending:
            # Paint the skeleton during the event-loop turn, then load.
            self._loading_pending = True
            self.history_view.show_loading()
            QTimer.singleShot(0, self._load_entries)
            return
        self._load_entries()

    def _load_entries(self) -> None:
        self._loading_pending = False
        query = self.search_input.text().strip()
        started = time.perf_counter()
        try:
            entries = self._query_entries(query)
        except StorageError as exc:
            self._slow_loads = False
            self._show_load_error(str(exc))
            return
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._slow_loads = elapsed_ms >= SLOW_LOAD_MS

        self.history_view.set_entries(
            entries,
            empty_kind=self._category,
            query=query,
            trimmed_ids=self._trimmed_ids,
        )
        self._update_footer(entries)
        self._sync_detail_panel()
        self._show_idle_status(len(entries))

    def _query_entries(self, query: str) -> list[ClipboardEntry]:
        entries = (
            self._repository.search(query)
            if query
            else self._repository.list_entries()
        )
        if self._category == "pinned":
            return [entry for entry in entries if entry.pinned]
        kind = CATEGORY_KINDS.get(self._category)
        if kind is not None:
            return [entry for entry in entries if classify_text(entry.text) is kind]
        return entries

    def _show_load_error(self, message: str) -> None:
        """Replace the list with an error state and drop every stale value.

        After a failed read nothing on screen can be confirmed any more, so the
        selection and the footer must stop describing the last successful load.
        Stored snippets are untouched: the next successful refresh reads them
        again.
        """
        self.history_view.show_error(message)
        self.history_view.clear_selection()
        self._sync_detail_panel()
        self.count_label.setText("History unavailable")
        self.clear_button.setEnabled(False)
        self._report_error(message)

    def _on_category_changed(self, category: str) -> None:
        self._category = category
        self._update_header()
        if category == "settings":
            self.content_stack.setCurrentWidget(self.settings_page)
            self._sync_settings()
        elif category in INFO_PAGES:
            self._show_about_page()
        else:
            self.content_stack.setCurrentWidget(self.history_page)
            self._refresh_history()
        self._apply_responsive_layout()

    def _on_entry_captured(self, entry: object) -> None:
        if self._category == "settings":
            # Keep the stored-count line truthful while the user is on Settings.
            self._sync_settings()
            return
        if self._category in INFO_PAGES:
            return
        self._refresh_history()
        # Show the fresh snippet, but never steal the selection while the user
        # is searching or has picked something else from the history.
        if isinstance(entry, ClipboardEntry) and not self.search_input.text().strip():
            self.history_view.select(entry.id)

    def _on_capture_truncated(self, entry: ClipboardEntry, original_length: int) -> None:
        self._trimmed_ids.add(entry.id)
        self._notify(
            f"Long snippet trimmed to {len(entry.text):,} of "
            f"{original_length:,} characters.",
            "warning",
        )

    def _on_capture_skipped(self, reason: str) -> None:
        """Report a skipped capture without exposing what was skipped."""
        message = SKIP_MESSAGES.get(
            reason, "Not saved: this clipboard content was excluded."
        )
        self._notify(message, "warning")
        self.statusBar().showMessage(message, 6000)

    def _on_entry_activated(self, entry_id: int) -> None:
        entry = self._get_entry(entry_id)
        if entry is None:
            self._refresh_history()
            return
        self.history_view.select(entry_id)
        if self._clipboard.copy_text(entry.text):
            self._notify("Copied to clipboard", "success", timeout_ms=2500)
            self.statusBar().showMessage("Copied to clipboard", 2500)

    def _on_pin_toggled(self, entry_id: int, pinned: bool) -> None:
        try:
            updated = self._repository.set_pinned(entry_id, pinned)
        except StorageError as exc:
            self._report_error(str(exc))
            self._refresh_history()
            return
        if not updated:
            # The snippet no longer exists, so the request changed nothing:
            # re-render the real history instead of claiming it was pinned.
            self._refresh_history()
            return
        self.history_view.select(entry_id)
        self._refresh_history()
        self._notify("Snippet pinned" if pinned else "Snippet unpinned", "success")

    def _on_delete_entry(self, entry_id: int) -> None:
        try:
            deleted = self._repository.delete(entry_id)
        except StorageError as exc:
            self._report_error(str(exc))
            return
        if not deleted:
            self._refresh_history()
            return
        self._refresh_history()
        self._notify("Snippet deleted", "success")

    def _on_clear_history(self) -> None:
        try:
            unpinned = self._repository.count(pinned=False)
            pinned = self._repository.count(pinned=True)
        except StorageError as exc:
            self._report_error(str(exc))
            return

        if unpinned == 0:
            self._notify("Nothing to clear - only pinned snippets remain.", "info")
            return
        if not self._confirm_clear_history(unpinned, pinned):
            return

        try:
            removed = self._repository.clear_unpinned()
        except StorageError as exc:
            self._report_error(str(exc))
            return

        self._refresh_history()
        noun = "snippet" if removed == 1 else "snippets"
        self._notify(f"Cleared {removed} unpinned {noun}. Pinned kept.", "success")

    def _confirm_clear_history(self, unpinned: int, pinned: int) -> bool:
        """Ask for confirmation before deleting unpinned history."""
        return confirm_clear_history(self, unpinned, pinned)

    def _on_selection_changed(self, entry: object) -> None:
        self._sync_detail_panel(entry if isinstance(entry, ClipboardEntry) else None)

    def _on_search_changed(self, query: str) -> None:
        self.clear_search_action.setVisible(bool(query))
        self._refresh_history()

    def _on_pause_changed(self, paused: bool) -> None:
        self._apply_pause_state(paused)
        self.settings_page.set_paused(paused)
        self._persist_pause_state(paused)
        self._show_idle_status(self.history_view.count())

    def _persist_pause_state(self, paused: bool) -> None:
        """Remember the pause state so a restart starts the same way.

        This runs on the transition signal, which every control (window
        button, tray action, banner action, Settings page) goes through, so a
        pause made from the tray is saved too. A failed write is logged rather
        than raised: the in-memory state is already correct, and the next
        transition tries again.
        """
        if self._preferences is None:
            return
        try:
            self._preferences.set_monitoring_paused(paused)
        except (RuntimeError, OSError, TypeError) as exc:
            logger.warning("Could not save the pause state: %s", exc)

    def _on_service_error(self, message: str) -> None:
        self._report_error(message)

    def _clear_search(self) -> None:
        if self.search_input.text():
            self.search_input.clear()
        self.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _focus_search(self) -> None:
        """Ctrl+K: focus the search field, switching back to All if needed."""
        if self._category not in HISTORY_PAGES:
            self.sidebar.set_current("all")
            self._on_category_changed("all")
        self.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _on_escape(self) -> None:
        """Escape unwinds one transient state; it never closes the window."""
        if self._category in HISTORY_PAGES and self.search_input.text():
            self._clear_search()
            return
        if self.search_input.hasFocus():
            self.search_input.clearFocus()
            if self.history_view.rows:
                self.history_view.focus_selected_card()
            return
        if self.notification.isVisible():
            self.notification.dismiss()

    # -------------------------------------------------------------- settings

    def apply_theme_mode(self, mode: str) -> bool:
        """Apply and persist an appearance choice. Returns whether it changed."""
        if mode not in THEMES:
            logger.warning("Ignoring unknown theme request %r", mode)
            return False
        if mode == theme().name:
            self.settings_page.set_theme(mode)
            return False
        app = QApplication.instance()
        if app is None:
            return False
        apply_theme(app, mode)
        if self._preferences is not None:
            self._preferences.set_theme(mode)
        self._refresh_theme_widgets()
        logger.info("Theme switched to %s", mode)
        return True

    def apply_history_limit(self, limit: int) -> bool:
        """Apply and persist the retention limit. Pinned rows are never removed."""
        try:
            validate_history_limit(limit)
        except ValueError as exc:
            # Bad input belongs next to the field it was typed into.
            self.settings_page.show_error(str(exc))
            return False
        try:
            removed = self._repository.set_history_limit(limit)
        except StorageError as exc:
            # A database failure is not invalid input: report it as the
            # operational error it is, and never claim the limit was applied.
            self.settings_page.show_error("")
            self._report_error(f"Could not apply the history limit: {exc}")
            return False

        if self._preferences is not None:
            self._preferences.set_history_limit(limit)
        self.settings_page.show_error("")
        self._sync_settings()
        self._refresh_history()

        if removed:
            noun = "snippet" if removed == 1 else "snippets"
            self._notify(
                f"History limit set to {limit:,}. Removed {removed} old unpinned "
                f"{noun}; pinned snippets kept.",
                "success",
            )
        else:
            self._notify(
                f"History limit set to {limit:,} unpinned snippets.", "success"
            )
        return True

    def apply_retention_days(self, days: object) -> bool:
        """Apply and persist the optional age limit (``None`` disables it)."""
        wanted = None if days is None else int(days)
        try:
            removed = self._repository.set_retention_days(wanted)
        except (ValueError, TypeError) as exc:
            self.settings_page.show_error(str(exc))
            return False
        except StorageError as exc:
            self.settings_page.show_error("")
            self._report_error(f"Could not apply the age limit: {exc}")
            return False

        if self._preferences is not None:
            self._preferences.set_retention_days(wanted)
        self.settings_page.show_error("")
        self._sync_settings()
        self._refresh_history()

        if wanted is None:
            self._notify("Age-based expiry is off.", "success")
        elif removed:
            noun = "snippet" if removed == 1 else "snippets"
            self._notify(
                f"Snippets older than {wanted:,} days removed ({removed:,} {noun}). "
                "Pinned snippets kept.",
                "success",
            )
        else:
            self._notify(
                f"Unpinned snippets older than {wanted:,} days will be deleted.",
                "success",
            )
        return True

    def apply_sensitive_detection(self, enabled: bool) -> bool:
        """Apply and persist the sensitive-content policy.

        Disabling it is a deliberate, explained choice: the policy is never
        changed silently, and ClipNest never pauses monitoring on its own
        because a rule fired.
        """
        self._clipboard.set_sensitive_detection(enabled)
        if self._preferences is not None:
            self._preferences.set_sensitive_detection(enabled)
        self.settings_page.set_sensitive(enabled)
        self._notify(
            "Sensitive-content detection enabled."
            if enabled
            else "Sensitive-content detection disabled - secrets can now be saved.",
            "success" if enabled else "warning",
        )
        return True

    def _sync_settings(self) -> None:
        """Push the current repository and service state into the Settings page."""
        page = self.settings_page
        page.set_storage_path(str(self._repository.database_path))
        page.set_encryption(self._repository.protector.is_encrypted)
        page.set_history_limit(self._repository.history_limit)
        page.set_retention_days(self._repository.retention_days)
        try:
            unpinned = self._repository.count(pinned=False)
            pinned = self._repository.count(pinned=True)
        except StorageError as exc:
            self._report_error(str(exc))
            return
        page.set_counts(unpinned, pinned)
        page.set_paused(self._clipboard.is_paused)
        page.set_sensitive(self._clipboard.sensitive_detection_enabled)
        page.set_theme(theme().name)

    def _refresh_theme_widgets(self) -> None:
        """Re-tint everything that cached a pixmap from the previous theme."""
        self.sidebar.refresh_theme()
        self.search_icon_action.setIcon(icons.icon("search", theme().text_faint, 14))
        self.clear_search_action.setIcon(
            icons.icon("close", theme().text_faint, 14)
        )
        self._apply_pause_state(self._clipboard.is_paused)
        self.notification.refresh_theme()
        self.pause_banner.refresh_theme()
        self.history_view.refresh_theme()
        self._refresh_history()
        self._sync_detail_panel()
        self.settings_page.refresh_theme()

    # ------------------------------------------------------------ internals

    def _sync_detail_panel(self, entry: ClipboardEntry | None = None) -> None:
        selected = entry or self.history_view.selected_entry
        trimmed = bool(selected and selected.id in self._trimmed_ids)
        self.detail_panel.set_entry(
            selected, self.history_view.selected_kind(), trimmed
        )

    def _update_header(self) -> None:
        title, subtitle = PAGE_COPY.get(self._category, PAGE_COPY["all"])
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)

    def _update_footer(self, entries: list[ClipboardEntry]) -> None:
        count = len(entries)
        self.count_label.setText(f"{count} {'snippet' if count == 1 else 'snippets'}")
        self.clear_button.setEnabled(any(not entry.pinned for entry in entries))

    def _show_about_page(self) -> None:
        self.content_stack.setCurrentWidget(self.info_page)
        storage_path = str(self._repository.database_path)

        self._set_info_row("primary", "Application", f"ClipNest {__version__}")
        self._set_info_row("secondary", "Platform", "Windows desktop (PySide6)")
        self._set_info_row("tertiary", "Storage", storage_path)
        self._set_info_row(
            "quaternary", "Privacy", "Local only - no cloud, no telemetry"
        )
        self.info_note.setText(
            "Clipboard snippets never leave this device. Pinned snippets are "
            "excluded from history trimming."
        )

    def _set_info_row(self, key: str, caption: str, value: str) -> None:
        self.info_rows[key].setText(value)
        getattr(self, f"_info_caption_{key}").setText(caption)

    def _apply_pause_state(self, paused: bool) -> None:
        self.pause_button.setText("Resume" if paused else "Pause")
        self.pause_button.setIcon(
            icons.icon("play" if paused else "pause", theme().text if paused else theme().text_muted, 14)
        )
        self.pause_button.setObjectName("PrimaryButton" if paused else "SecondaryButton")
        self.pause_button.setAccessibleName(
            "Resume clipboard monitoring" if paused else "Pause clipboard monitoring"
        )
        self.pause_button.style().unpolish(self.pause_button)
        self.pause_button.style().polish(self.pause_button)

        if paused:
            self.pause_banner.show_message(
                "Monitoring paused - copied text is not being saved.",
                "warning",
                timeout_ms=None,
                action_text="Resume",
                icon_name="pause",
            )
        else:
            self.pause_banner.dismiss()

    def _apply_responsive_layout(self) -> None:
        width = self.width()
        self.sidebar.set_compact(width < COMPACT_SIDEBAR_MAX_WIDTH)
        show_detail = (
            width >= DETAIL_PANEL_MIN_WIDTH and self._category in HISTORY_PAGES
        )
        self.detail_panel.setVisible(show_detail)

    def _notify(
        self, message: str, severity: str = "info", timeout_ms: int | None = 3500
    ) -> None:
        self.notification.show_message(message, severity, timeout_ms)

    def _show_idle_status(self, count: int) -> None:
        state = "Paused" if self._clipboard.is_paused else "Monitoring"
        self.statusBar().showMessage(
            f"{state} - {count} {'entry' if count == 1 else 'entries'}"
        )

    def _report_error(self, message: str) -> None:
        logger.warning("Main window error: %s", message)
        self._notify(message, "error", timeout_ms=8000)
        self.statusBar().showMessage(message, 8000)

    def _get_entry(self, entry_id: int) -> ClipboardEntry | None:
        try:
            return self._repository.get(entry_id)
        except StorageError as exc:
            self._report_error(str(exc))
            return None

    def _center_on_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._apply_responsive_layout()
