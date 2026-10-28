"""Test doubles for the clipboard service and at-rest protection.

The real ``QClipboard`` is never touched by the test suite: these fakes expose
the same minimal surface (a ``dataChanged`` signal, ``text()`` and
``setText()``) so capture, suppression and failure paths can be exercised
without reading or writing the system clipboard. ``FakeClipboardFlags`` stands
in for the Win32 clipboard privacy markers in the same way, and
``FakeProtector`` stands in for Windows DPAPI so no test unlocks (or writes)
the developer's real protected data.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from clipnest.core.clipboard_flags import ClipboardPrivacy
from clipnest.core.protection import ProtectionError


class FakeClipboard(QObject):
    """In-memory stand-in for ``QClipboard``."""

    dataChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self.read_error: Exception | None = None
        self.emit_on_set = True
        self.read_calls = 0

    def text(self) -> str:
        """Return the current fake clipboard text, or raise a configured error."""
        self.read_calls += 1
        if self.read_error is not None:
            raise self.read_error
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802 - mirrors QClipboard
        """Mirror ``QClipboard.setText``, optionally announcing the change."""
        self._text = text
        if self.emit_on_set:
            self.dataChanged.emit()

    def simulate_copy(self, text: str) -> None:
        """Simulate another application copying ``text``."""
        self._text = text
        self.dataChanged.emit()


class FakeClipboardFlags:
    """Scriptable stand-in for the Windows clipboard privacy markers."""

    def __init__(
        self,
        privacy: ClipboardPrivacy | None = None,
        supported: bool = True,
        error: Exception | None = None,
    ) -> None:
        self.is_supported = supported
        self.privacy = privacy if privacy is not None else ClipboardPrivacy()
        self.error = error
        self.reads = 0

    def read(self) -> ClipboardPrivacy:
        """Return the configured marker state, or raise the configured error."""
        self.reads += 1
        if self.error is not None:
            raise self.error
        return self.privacy


class FakeProtector:
    """Reversible, non-DPAPI protector.

    The stored bytes are XOR-masked and prefixed, which is enough to prove the
    database never holds the snippet as readable text without depending on the
    Windows account running the tests.
    """

    name = "fake"
    is_encrypted = True
    PREFIX = b"fake:"

    def __init__(self, key: int = 0x5A) -> None:
        self._key = key
        self.protects = 0
        self.unprotects = 0

    def protect(self, text: str) -> bytes:
        self.protects += 1
        masked = bytes(byte ^ self._key for byte in text.encode("utf-8"))
        return self.PREFIX + masked

    def unprotect(self, blob: bytes) -> str:
        self.unprotects += 1
        data = bytes(blob)
        if not data.startswith(self.PREFIX):
            raise ProtectionError("value was not protected by this protector")
        try:
            return bytes(byte ^ self._key for byte in data[len(self.PREFIX) :]).decode(
                "utf-8"
            )
        except UnicodeDecodeError as exc:
            raise ProtectionError("protected value is not text") from exc


class FailingProtector(FakeProtector):
    """Protector whose ``protect`` always fails, for migration rollback tests."""

    fail_after: int | None = None

    def __init__(self, fail_after: int | None = None) -> None:
        super().__init__()
        self.fail_after = fail_after

    def protect(self, text: str) -> bytes:
        if self.fail_after is None or self.protects >= self.fail_after:
            raise ProtectionError("protector is unavailable")
        return super().protect(text)


class ForeignProtector(FakeProtector):
    """Protector that writes fine but cannot read another key's values."""

    def unprotect(self, blob: bytes) -> str:
        raise ProtectionError("value belongs to another Windows account")
