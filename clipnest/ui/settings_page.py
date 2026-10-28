"""Settings page: appearance, history retention, privacy, and shortcuts.

The page is presentation only. It reports user intent as signals and is told
what to display through the ``set_*`` methods, so the window stays the single
place that touches the repository, the clipboard service, and preferences.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from clipnest.core.storage import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from clipnest.preferences import (
    MAX_HISTORY_LIMIT,
    MIN_HISTORY_LIMIT,
    validate_history_limit,
)
from clipnest.ui import icons
from clipnest.ui.theme import theme

CONTENT_MAX_WIDTH = 760
LIMIT_FIELD_WIDTH = 96
EXPIRY_FIELD_WIDTH = 80
DEFAULT_EXPIRY_DAYS = 30

THEME_LABELS = (("dark", "Dark"), ("light", "Light"))

SHORTCUTS = (
    ("Ctrl+K", "Focus the search field"),
    ("Esc", "Clear the search, then leave the search field"),
)


class WrappedLabel(QLabel):
    """A word-wrapped label that keeps the height its text needs.

    ``QLabel`` reports a single-line ``minimumSizeHint`` even with word wrap
    enabled, so a card inside a scroll area can be squeezed until the last
    wrapped line is clipped. Re-deriving the minimum height from the current
    width stops that, and the value only depends on the width, so one extra
    layout pass settles it.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        needed = self.heightForWidth(event.size().width())
        if needed > 0:
            self.setMinimumHeight(needed)


class SettingsPage(QWidget):
    """Editable application settings, shown in the main window's content area."""

    theme_selected = Signal(str)
    history_limit_requested = Signal(int)
    retention_requested = Signal(object)  # int days, or None to disable
    pause_toggled = Signal()
    clear_requested = Signal()
    sensitive_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        self._theme = theme().name
        self._paused = False
        self._sensitive = True
        self._building = False

        scroll = QScrollArea(self)
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("SettingsBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 8, 0)
        body_layout.setSpacing(12)
        body_layout.addWidget(self._build_appearance(), alignment=Qt.AlignmentFlag.AlignTop)
        body_layout.addWidget(self._build_history(), alignment=Qt.AlignmentFlag.AlignTop)
        body_layout.addWidget(self._build_privacy(), alignment=Qt.AlignmentFlag.AlignTop)
        body_layout.addWidget(self._build_shortcuts(), alignment=Qt.AlignmentFlag.AlignTop)
        body_layout.addStretch(1)
        scroll.setWidget(body)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(scroll)

        self.set_theme(self._theme)
        self.set_paused(False)
        self.set_sensitive(True)
        self.set_encryption(True)

    # -------------------------------------------------------------------- API

    def set_theme(self, mode: str) -> None:
        """Show ``mode`` as the active choice without emitting anything."""
        button = self.theme_buttons.get(mode)
        if button is None:
            return
        self._building = True
        try:
            button.setChecked(True)
        finally:
            self._building = False
        self._theme = mode

    def set_history_limit(self, limit: int) -> None:
        """Show the limit currently applied by the repository."""
        self.limit_input.setValue(limit)

    def set_retention_days(self, days: int | None) -> None:
        """Show the age limit currently applied by the repository."""
        self._building = True
        try:
            self.expiry_check.setChecked(days is not None)
            if days is not None:
                self.expiry_days_input.setValue(int(days))
            self.expiry_days_input.setEnabled(days is not None)
        finally:
            self._building = False

    def set_encryption(self, enabled: bool) -> None:
        """State plainly whether stored snippets are protected at rest."""
        self._encrypted = bool(enabled)
        if self._encrypted:
            self.encryption_note.setText(
                "Snippets are encrypted at rest with Windows DPAPI and can only "
                "be read by this Windows account on this machine."
            )
        else:
            self.encryption_note.setText(
                "Snippets are stored unencrypted: Windows DPAPI is not available "
                "on this platform. Anyone who can read the database file can "
                "read the history."
            )

    def set_counts(self, unpinned: int, pinned: int) -> None:
        """Describe what is stored right now, next to the limit."""
        unpinned_noun = "snippet" if unpinned == 1 else "snippets"
        pinned_noun = "snippet" if pinned == 1 else "snippets"
        self.limit_note.setText(
            f"Currently storing {unpinned:,} unpinned {unpinned_noun} and "
            f"{pinned:,} pinned {pinned_noun}. Pinned snippets are never counted "
            "against the limit and are never deleted by it."
        )

    def set_paused(self, paused: bool) -> None:
        """Mirror the clipboard service's pause state."""
        self._paused = bool(paused)
        self.pause_button.setText(
            "Resume monitoring" if self._paused else "Pause monitoring"
        )
        self.pause_button.setIcon(
            icons.icon(
                "play" if self._paused else "pause",
                theme().text if self._paused else theme().text_muted,
                14,
            )
        )
        self.pause_button.setAccessibleName(
            "Resume capture" if self._paused else "Pause capture"
        )
        self.pause_state_label.setText(
            "Capture is paused: copied text is not being saved."
            if self._paused
            else "Capture is active: copied text is saved on this device."
        )

    def set_storage_path(self, path: str) -> None:
        """Show where the local history database lives."""
        self.storage_label.setText(path)
        self.storage_label.setToolTip(path)

    def set_sensitive(self, enabled: bool) -> None:
        """Mirror the sensitive-content policy of the clipboard service."""
        self._sensitive = bool(enabled)
        self._building = True
        try:
            self.sensitive_check.setText("Skip snippets that look like secrets")
            self.sensitive_check.setChecked(self._sensitive)
        finally:
            self._building = False
        self.sensitive_note.setText(
            "Sensitive-content detection is on: content matching a password, "
            "key, one-time-code or card-number rule is not saved."
            if self._sensitive
            else "Sensitive-content detection is off: everything you copy is "
            "saved, including passwords, keys and card numbers."
        )

    def show_error(self, message: str) -> None:
        """Show (or clear, with an empty string) the limit validation message.

        Reserved for input the user can correct here. Operational failures
        such as an unavailable database are not validation problems; the window
        reports those through its error banner and status bar.
        """
        self.limit_error.setText(message)
        self.limit_error.setVisible(bool(message))

    def refresh_theme(self) -> None:
        """Re-tint the icons this page drew with the previous palette."""
        self.set_theme(theme().name)
        self.set_paused(self._paused)
        self.set_sensitive(self._sensitive)

    # ------------------------------------------------------------- sections

    def _card(self, title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(self)
        card.setObjectName("Card")
        card.setMaximumWidth(CONTENT_MAX_WIDTH)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)

        heading = QLabel(title, card)
        heading.setObjectName("SettingsHeading")

        hint = WrappedLabel(description, card)
        hint.setObjectName("SettingsHint")

        layout.addWidget(heading)
        layout.addWidget(hint)
        return card, layout

    def _build_appearance(self) -> QFrame:
        card, layout = self._card(
            "Appearance",
            "Choose how ClipNest looks. The change applies immediately and is "
            "remembered the next time ClipNest starts.",
        )

        row = QWidget(card)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 4, 0, 0)
        row_layout.setSpacing(8)

        group = QButtonGroup(self)
        group.setExclusive(True)
        self.theme_buttons: dict[str, QPushButton] = {}
        for mode, label in THEME_LABELS:
            button = QPushButton(label, row)
            button.setObjectName("ChoiceButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(f"Use the {label.lower()} theme")
            button.clicked.connect(lambda _checked=False, m=mode: self._choose_theme(m))
            group.addButton(button)
            row_layout.addWidget(button)
            self.theme_buttons[mode] = button

        row_layout.addStretch(1)
        layout.addWidget(row)
        return card

    def _build_history(self) -> QFrame:
        card, layout = self._card(
            "History",
            "How many unpinned snippets ClipNest keeps, and optionally how long. "
            "Applying either rule deletes the snippets it excludes. Pinned "
            "snippets are never counted against the limit, never expire, and "
            "are never deleted by either rule.",
        )

        row = QWidget(card)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 4, 0, 0)
        row_layout.setSpacing(10)

        self.limit_input = QSpinBox(row)
        self.limit_input.setObjectName("HistoryLimitInput")
        self.limit_input.setRange(MIN_HISTORY_LIMIT, MAX_HISTORY_LIMIT)
        self.limit_input.setSingleStep(10)
        self.limit_input.setKeyboardTracking(False)
        self.limit_input.setFixedWidth(LIMIT_FIELD_WIDTH)
        self.limit_input.setAccessibleName("Maximum number of unpinned snippets")

        unit = QLabel("unpinned snippets", row)
        unit.setObjectName("SettingsHint")

        self.apply_limit_button = QPushButton("Apply", row)
        self.apply_limit_button.setObjectName("SecondaryButton")
        self.apply_limit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_limit_button.clicked.connect(self._request_limit)

        row_layout.addWidget(self.limit_input)
        row_layout.addWidget(unit)
        row_layout.addStretch(1)
        row_layout.addWidget(self.apply_limit_button)

        self.limit_note = WrappedLabel("", card)
        self.limit_note.setObjectName("SettingsHint")

        self.limit_error = WrappedLabel("", card)
        self.limit_error.setObjectName("SettingsError")
        self.limit_error.setVisible(False)

        layout.addWidget(row)
        layout.addWidget(self.limit_note)
        layout.addWidget(self.limit_error)

        expiry_row = QWidget(card)
        expiry_layout = QHBoxLayout(expiry_row)
        expiry_layout.setContentsMargins(0, 6, 0, 0)
        expiry_layout.setSpacing(10)

        self.expiry_check = QCheckBox("Delete unpinned snippets older than", expiry_row)
        self.expiry_check.setObjectName("SettingsCheck")
        self.expiry_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expiry_check.setAccessibleName("Expire unpinned snippets by age")
        self.expiry_check.toggled.connect(self._on_expiry_toggled)

        self.expiry_days_input = QSpinBox(expiry_row)
        self.expiry_days_input.setObjectName("HistoryLimitInput")
        self.expiry_days_input.setRange(MIN_RETENTION_DAYS, MAX_RETENTION_DAYS)
        self.expiry_days_input.setValue(DEFAULT_EXPIRY_DAYS)
        self.expiry_days_input.setFixedWidth(EXPIRY_FIELD_WIDTH)
        self.expiry_days_input.setAccessibleName("Maximum snippet age in days")
        self.expiry_days_input.setEnabled(False)

        expiry_unit = QLabel("days", expiry_row)
        expiry_unit.setObjectName("SettingsHint")

        self.apply_expiry_button = QPushButton("Apply", expiry_row)
        self.apply_expiry_button.setObjectName("SecondaryButton")
        self.apply_expiry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_expiry_button.clicked.connect(self._request_retention)

        expiry_layout.addWidget(self.expiry_check)
        expiry_layout.addWidget(self.expiry_days_input)
        expiry_layout.addWidget(expiry_unit)
        expiry_layout.addStretch(1)
        expiry_layout.addWidget(self.apply_expiry_button)

        layout.addWidget(expiry_row)
        return card

    def _build_privacy(self) -> QFrame:
        card, layout = self._card(
            "Privacy",
            "Clipboard history is stored only on this device, in a local "
            "SQLite database. Nothing is uploaded: there is no account, no "
            "cloud sync, no analytics and no telemetry. ClipNest also honours "
            "the Windows clipboard privacy markers that source applications "
            "set, so content they exclude from monitoring or from the clipboard "
            "history is not read or saved.",
        )

        self.storage_label = WrappedLabel("", card)
        self.storage_label.setObjectName("SettingsPath")
        self.storage_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.encryption_note = WrappedLabel("", card)
        self.encryption_note.setObjectName("SettingsHint")
        self._encrypted = True

        self.sensitive_check = QCheckBox(
            "Skip snippets that look like secrets", card
        )
        self.sensitive_check.setObjectName("SettingsCheck")
        self.sensitive_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sensitive_check.setAccessibleName("Skip snippets that look like secrets")
        self.sensitive_check.toggled.connect(self._on_sensitive_toggled)

        self.sensitive_note = WrappedLabel("", card)
        self.sensitive_note.setObjectName("SettingsHint")

        caution = WrappedLabel(
            "Detection is a best-effort filter, not a guarantee. It recognises "
            "private-key blocks, common provider API keys, password/hidden-key "
            "assignments, one-time codes and payment-card numbers, but it "
            "cannot recognise every secret - a password that looks like "
            "ordinary text is still saved. Turning detection off allows such "
            "content into the history.",
            card,
        )
        caution.setObjectName("SettingsHint")
        self.privacy_note = caution

        self.pause_state_label = WrappedLabel("", card)
        self.pause_state_label.setObjectName("SettingsHint")

        row = QWidget(card)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 4, 0, 0)
        row_layout.setSpacing(8)

        self.pause_button = QPushButton("Pause monitoring", row)
        self.pause_button.setObjectName("SecondaryButton")
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.clicked.connect(self.pause_toggled)

        self.clear_button = QPushButton("Clear unpinned history", row)
        self.clear_button.setObjectName("DangerButton")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setToolTip(
            "Delete every unpinned snippet. Pinned snippets are kept."
        )
        self.clear_button.clicked.connect(self.clear_requested)

        row_layout.addWidget(self.pause_button)
        row_layout.addWidget(self.clear_button)
        row_layout.addStretch(1)

        layout.addWidget(self.storage_label)
        layout.addWidget(self.encryption_note)
        layout.addWidget(self.sensitive_check)
        layout.addWidget(self.sensitive_note)
        layout.addWidget(caution)
        layout.addWidget(self.pause_state_label)
        layout.addWidget(row)
        return card

    def _build_shortcuts(self) -> QFrame:
        card, layout = self._card(
            "Keyboard shortcuts",
            "Shortcuts work while the ClipNest window is focused.",
        )

        for keys, description in SHORTCUTS:
            row = QWidget(card)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(12)

            key_label = QLabel(keys, row)
            key_label.setObjectName("ShortcutKey")
            key_label.setFixedWidth(90)
            key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            text = WrappedLabel(description, row)
            text.setObjectName("SettingsHint")

            row_layout.addWidget(key_label)
            row_layout.addWidget(text, stretch=1)
            layout.addWidget(row)

        return card

    # ------------------------------------------------------------ internals

    def _choose_theme(self, mode: str) -> None:
        if self._building or mode == self._theme:
            return
        self._theme = mode
        self.theme_selected.emit(mode)

    def _on_sensitive_toggled(self, checked: bool) -> None:
        if self._building or checked == self._sensitive:
            return
        self.sensitive_toggled.emit(bool(checked))

    def _on_expiry_toggled(self, checked: bool) -> None:
        self.expiry_days_input.setEnabled(bool(checked))

    def _request_retention(self) -> None:
        days = self.expiry_days_input.value()
        if not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS:
            self.show_error(
                f"Choose between {MIN_RETENTION_DAYS} and "
                f"{MAX_RETENTION_DAYS} days."
            )
            return
        self.show_error("")
        self.retention_requested.emit(days if self.expiry_check.isChecked() else None)

    def _request_limit(self) -> None:
        value = self.limit_input.value()
        try:
            validate_history_limit(value)
        except ValueError as exc:
            self.show_error(str(exc))
            return
        self.show_error("")
        self.history_limit_requested.emit(value)
