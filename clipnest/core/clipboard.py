"""Clipboard monitoring built on Qt's ``QClipboard.dataChanged`` signal.

No polling: the service reacts to change notifications, ignores anything that
is not plain text, and hands persisted entries back to the UI via
``entry_captured``. Pasting from within ClipNest (click-to-copy) is suppressed
so the app never grows its own history, and a repeat copy is recognised against
the newest stored snippet, so it stays a single entry even after the history
was cleared, trimmed, or deleted from.

Failures never crash the application and are never silently dropped: they are
logged (message only, never clipboard content) and re-emitted through
``error_occurred`` so the UI can show them.

The capture pipeline runs in this order, and each step is cheaper than the next
one it protects: paused check, Windows clipboard privacy markers, clipboard
text, length/whitespace rules, self-copy suppression, sensitive-content rule,
duplicate check, persistence. Marker checks run before the text is read so
content a source application excluded is never even looked at, and duplicate
checks run last so skipped content never costs a database read.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QClipboard

from clipnest.core import sensitive
from clipnest.core.clipboard_flags import (
    CapturePolicy,
    ClipboardFlagsProvider,
    UnsupportedClipboardFlags,
    read_capture_policy,
)
from clipnest.core.sensitive import SensitiveFinding
from clipnest.core.storage import ClipboardEntry, ClipboardRepository, StorageError

logger = logging.getLogger(__name__)

DEFAULT_MAX_TEXT_LENGTH = 10_000
SELF_COPY_SUPPRESSION_SECONDS = 2.0

# Skip reason emitted for content that matched a sensitive-data rule. The value
# never identifies which value matched, only that a rule fired.
SKIP_SENSITIVE = "sensitive"

SensitiveDetector = Callable[[str], SensitiveFinding | None]


class ClipboardService(QObject):
    """Turns clipboard changes into stored :class:`ClipboardEntry` records."""

    entry_captured = Signal(object)  # ClipboardEntry
    capture_truncated = Signal(object, int)  # (stored ClipboardEntry, original length)
    capture_skipped = Signal(str)  # CapturePolicy value; never content
    paused_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(
        self,
        clipboard: QClipboard,
        repository: ClipboardRepository,
        max_text_length: int = DEFAULT_MAX_TEXT_LENGTH,
        self_copy_window: float = SELF_COPY_SUPPRESSION_SECONDS,
        parent: QObject | None = None,
        flags_provider: ClipboardFlagsProvider | None = None,
        sensitive_detector: SensitiveDetector | None = None,
        sensitive_enabled: bool = True,
        paused: bool = False,
    ) -> None:
        super().__init__(parent)
        if max_text_length <= 0:
            raise ValueError("max_text_length must be positive")
        self._clipboard = clipboard
        self._repository = repository
        self._max_text_length = max_text_length
        self._self_copy_window = self_copy_window
        # The composition root injects the real platform provider; the default
        # is the inert one so no test or embedder reaches the native clipboard
        # by accident.
        self._flags_provider = (
            flags_provider if flags_provider is not None else UnsupportedClipboardFlags()
        )
        self._detector: SensitiveDetector = (
            sensitive_detector if sensitive_detector is not None else sensitive.detect
        )
        self._sensitive_enabled = bool(sensitive_enabled)
        self._running = False
        # A restored pause state is applied here, before ``start()`` connects
        # the clipboard signal, so there is no moment in which a copy could be
        # recorded while the user believes monitoring is still paused.
        self._paused = bool(paused)
        self._suppressed_text: str | None = None
        self._suppression_deadline = 0.0

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Begin listening for clipboard changes."""
        if self._running:
            return
        self._clipboard.dataChanged.connect(self._on_clipboard_changed)
        self._running = True

    def stop(self) -> None:
        """Stop listening. Safe to call more than once."""
        if not self._running:
            return
        try:
            self._clipboard.dataChanged.disconnect(self._on_clipboard_changed)
        except (RuntimeError, TypeError):
            # Qt raises RuntimeError when the connection is already gone.
            logger.debug("Clipboard change handler was already disconnected")
        self._running = False

    # ------------------------------------------------------------ pause state

    @property
    def is_paused(self) -> bool:
        """Whether incoming clipboard changes are currently ignored."""
        return self._paused

    @property
    def is_running(self) -> bool:
        """Whether the service is connected to the clipboard."""
        return self._running

    @property
    def max_text_length(self) -> int:
        """Maximum number of characters stored per clipboard entry."""
        return self._max_text_length

    def pause(self) -> None:
        """Stop recording clipboard changes without disconnecting."""
        self.set_paused(True)

    def resume(self) -> None:
        """Resume recording clipboard changes."""
        self.set_paused(False)

    def toggle_paused(self) -> bool:
        """Flip the paused state and return the new value."""
        self.set_paused(not self._paused)
        return self._paused

    def set_paused(self, paused: bool) -> None:
        """Set the paused state, emitting ``paused_changed`` on transitions."""
        if self._paused == paused:
            return
        self._paused = paused
        # An event only: never what was on the clipboard at the time.
        logger.info("Clipboard monitoring %s", "paused" if paused else "resumed")
        self.paused_changed.emit(paused)

    # ------------------------------------------------------------- copy-back

    def copy_text(self, text: str) -> bool:
        """Copy ``text`` back to the clipboard without recording it again.

        The matching ``dataChanged`` notification (immediate on some platforms,
        delayed on others) is recognised by content and swallowed once.
        """
        if not text:
            return False
        self._suppressed_text = text
        self._suppression_deadline = time.monotonic() + self._self_copy_window
        try:
            self._clipboard.setText(text)
        except RuntimeError as exc:
            self._suppressed_text = None
            self._report_error(f"Could not copy to the clipboard: {exc}")
            return False
        return True

    # -------------------------------------------------------------- handlers

    @property
    def flags_provider(self) -> ClipboardFlagsProvider:
        """The clipboard privacy-marker provider used for each capture."""
        return self._flags_provider

    @property
    def sensitive_detection_enabled(self) -> bool:
        """Whether content matching a sensitive-data rule is refused."""
        return self._sensitive_enabled

    def set_sensitive_detection(self, enabled: bool) -> None:
        """Turn sensitive-content detection on or off.

        The preference belongs to the user: ClipNest never pauses itself
        because a rule fired, and never redacts part of a match instead.
        """
        self._sensitive_enabled = bool(enabled)
        logger.info(
            "Sensitive-content detection %s",
            "enabled" if self._sensitive_enabled else "disabled",
        )

    def _on_clipboard_changed(self) -> None:
        if self._paused:
            return
        if not self._privacy_allows_capture():
            return
        try:
            text = self._clipboard.text()
        except Exception as exc:  # Qt can fail while another app owns the clipboard
            self._report_error(f"Clipboard is unavailable: {exc}")
            return

        # Trim first: the truncated value is what a repeat copy produces too, so
        # an oversized snippet must be deduplicated on its stored form rather
        # than on the full clipboard text.
        original_length = len(text)
        stored_text = text[: self._max_text_length]
        if not stored_text.strip():
            return
        if self._is_self_copy(text):
            return
        if not self._passes_sensitive_rules(stored_text):
            return

        # The newest stored snippet is the source of truth, so a repeat copy is
        # still ignored after the history was cleared, trimmed, or deleted from.
        try:
            latest = self._repository.latest_text()
        except StorageError as exc:
            self._report_error(str(exc))
            return
        if stored_text == latest:
            return

        try:
            entry = self._repository.add(stored_text)
        except StorageError as exc:
            self._report_error(str(exc))
            return

        if original_length > self._max_text_length:
            # Only the clipped value is stored; say so rather than implying the
            # full clipboard text was kept.
            self.capture_truncated.emit(entry, original_length)
        self.entry_captured.emit(entry)

    def _privacy_allows_capture(self) -> bool:
        """Ask the platform markers whether this change may be processed.

        The read is synchronous and happens before the clipboard text is
        touched, so excluded content is never even read. An unknown marker
        state blocks capture and is announced without any content.
        """
        policy = read_capture_policy(self._flags_provider)
        if policy is CapturePolicy.ALLOW:
            return True
        logger.info("Capture skipped: %s", policy.value)
        self.capture_skipped.emit(policy.value)
        return False

    def _passes_sensitive_rules(self, stored_text: str) -> bool:
        """Apply the sensitive-content policy to the value that would be stored.

        Runs after the length rules (so only the stored text is scanned) and
        before the duplicate check (so a refused value costs no database read).
        """
        if not self._sensitive_enabled:
            return True
        finding = self._detector(stored_text)
        if finding is None:
            return True
        # Only the category is logged: never the value, the line, or a prefix.
        logger.info("Capture skipped: sensitive rule %s", finding.kind.value)
        self.capture_skipped.emit(SKIP_SENSITIVE)
        return False

    def _is_self_copy(self, text: str) -> bool:
        """Return ``True`` when ``text`` is the echo of our own ``copy_text``."""
        if self._suppressed_text is None:
            return False
        if time.monotonic() > self._suppression_deadline:
            self._suppressed_text = None
            return False
        if text != self._suppressed_text:
            return False
        self._suppressed_text = None
        return True

    # -------------------------------------------------------------- internals

    def _report_error(self, message: str) -> None:
        """Log and surface a failure without leaking clipboard content."""
        logger.warning("Clipboard service error: %s", message)
        self.error_occurred.emit(message)
