"""Tests for the Windows clipboard privacy markers.

Nothing here opens the real clipboard: the marker decision table is pure logic,
and the Win32 reader is exercised against a fake ``user32``/``kernel32`` pair
that records every call, so handle cleanup and payload validation are verified
without the developer's clipboard being involved.
"""

from __future__ import annotations

import ctypes

import pytest

from clipnest.core.clipboard_flags import (
    CLOUD_FORMAT_NAME,
    EXCLUDE_FORMAT_NAME,
    HISTORY_FORMAT_NAME,
    CapturePolicy,
    ClipboardFlagsError,
    ClipboardPrivacy,
    UnsupportedClipboardFlags,
    WindowsClipboardFlags,
    decide_capture,
    read_capture_policy,
)
from tests.fakes import FakeClipboardFlags

FORMAT_IDS = {
    EXCLUDE_FORMAT_NAME: 1001,
    HISTORY_FORMAT_NAME: 1002,
    CLOUD_FORMAT_NAME: 1003,
}
EXCLUDE_ID = FORMAT_IDS[EXCLUDE_FORMAT_NAME]
HISTORY_ID = FORMAT_IDS[HISTORY_FORMAT_NAME]
CLOUD_ID = FORMAT_IDS[CLOUD_FORMAT_NAME]


class FakeUser32:
    """Minimal stand-in for the ``user32`` clipboard entry points."""

    def __init__(self, payloads=None, open_failures: int = 0, bad_formats=()) -> None:
        self.payloads: dict[int, bytes] = dict(payloads or {})
        self.open_failures = open_failures
        self.bad_formats = set(bad_formats)
        self.open_calls = 0
        self.close_calls = 0
        self.register_calls: list[str] = []
        self.handles: dict[int, bytes] = {}
        self._next_handle = 5000

    def RegisterClipboardFormatW(self, name: str) -> int:
        self.register_calls.append(name)
        if name in self.bad_formats:
            return 0
        return FORMAT_IDS[name]

    def OpenClipboard(self, hwnd) -> int:
        self.open_calls += 1
        if self.open_failures > 0:
            self.open_failures -= 1
            return 0
        return 1

    def CloseClipboard(self) -> int:
        self.close_calls += 1
        return 1

    def GetClipboardData(self, format_id: int) -> int:
        data = self.payloads.get(format_id)
        if data is None:
            return 0
        handle = self._next_handle
        self._next_handle += 1
        self.handles[handle] = data
        return handle


class FakeKernel32:
    """Minimal stand-in for the ``kernel32`` global-memory entry points."""

    def __init__(self, user32: FakeUser32, fail_lock: bool = False) -> None:
        self._user32 = user32
        self.fail_lock = fail_lock
        self._buffers: dict[int, ctypes.Array] = {}
        self.locked: list[int] = []
        self.unlocked: list[int] = []

    def GlobalSize(self, handle: int) -> int:
        return len(self._user32.handles.get(handle, b""))

    def GlobalLock(self, handle: int):
        if self.fail_lock:
            return None
        data = self._user32.handles[handle]
        buffer = ctypes.create_string_buffer(data, max(len(data), 1))
        self._buffers[handle] = buffer
        self.locked.append(handle)
        return ctypes.addressof(buffer)

    def GlobalUnlock(self, handle: int) -> int:
        self.unlocked.append(handle)
        return 1


def make_reader(user32: FakeUser32, kernel32: FakeKernel32 | None = None):
    """Build a reader around fake Win32 modules (never the real clipboard)."""
    reader = WindowsClipboardFlags()
    reader._user32 = user32
    reader._kernel32 = kernel32 if kernel32 is not None else FakeKernel32(user32)
    return reader


def dword(value: int) -> bytes:
    return int(value).to_bytes(4, "little")


# --------------------------------------------------------------- decision table


@pytest.mark.parametrize(
    ("privacy", "expected"),
    [
        (ClipboardPrivacy(), CapturePolicy.ALLOW),
        (ClipboardPrivacy(excluded=True), CapturePolicy.BLOCK_MARKER),
        (
            ClipboardPrivacy(excluded=True, history_allowed=True),
            CapturePolicy.BLOCK_MARKER,
        ),
        (ClipboardPrivacy(history_allowed=False), CapturePolicy.BLOCK_HISTORY),
        (
            ClipboardPrivacy(history_allowed=False, cloud_allowed=True),
            CapturePolicy.BLOCK_HISTORY,
        ),
        (ClipboardPrivacy(history_allowed=True), CapturePolicy.ALLOW),
        (ClipboardPrivacy(history_invalid=True), CapturePolicy.BLOCK_INVALID),
        (
            ClipboardPrivacy(history_invalid=True, history_allowed=True),
            CapturePolicy.BLOCK_INVALID,
        ),
        (ClipboardPrivacy(cloud_allowed=False), CapturePolicy.ALLOW),
        (ClipboardPrivacy(cloud_allowed=True), CapturePolicy.ALLOW),
    ],
)
def test_decision_table(privacy: ClipboardPrivacy, expected: CapturePolicy) -> None:
    assert decide_capture(privacy) is expected


def test_unsupported_platform_allows_capture_without_reading() -> None:
    provider = UnsupportedClipboardFlags()

    assert provider.is_supported is False
    assert provider.read() == ClipboardPrivacy()
    assert read_capture_policy(provider) is CapturePolicy.ALLOW


def test_unreadable_markers_fail_closed() -> None:
    provider = FakeClipboardFlags(error=ClipboardFlagsError("locked"))

    assert read_capture_policy(provider) is CapturePolicy.BLOCK_UNREADABLE


def test_unexpected_provider_failure_fails_closed() -> None:
    provider = FakeClipboardFlags(error=OSError("boom"))

    assert read_capture_policy(provider) is CapturePolicy.BLOCK_UNREADABLE


def test_no_objection_allows_capture() -> None:
    assert read_capture_policy(FakeClipboardFlags()) is CapturePolicy.ALLOW


# ------------------------------------------------------------- native reader


def test_absent_markers_report_nothing_and_allow_capture() -> None:
    user32 = FakeUser32()
    privacy = make_reader(user32).read()

    assert privacy == ClipboardPrivacy()
    assert decide_capture(privacy) is CapturePolicy.ALLOW


def test_exclusion_marker_is_presence_based() -> None:
    user32 = FakeUser32({EXCLUDE_ID: b""})
    privacy = make_reader(user32).read()

    assert privacy.excluded is True
    assert decide_capture(privacy) is CapturePolicy.BLOCK_MARKER


def test_history_marker_zero_blocks_capture() -> None:
    user32 = FakeUser32({HISTORY_ID: dword(0)})
    privacy = make_reader(user32).read()

    assert privacy.history_allowed is False
    assert privacy.history_invalid is False
    assert decide_capture(privacy) is CapturePolicy.BLOCK_HISTORY


def test_history_marker_nonzero_allows_capture() -> None:
    user32 = FakeUser32({HISTORY_ID: dword(1)})
    privacy = make_reader(user32).read()

    assert privacy.history_allowed is True
    assert decide_capture(privacy) is CapturePolicy.ALLOW


def test_cloud_marker_is_reported_but_never_blocks() -> None:
    user32 = FakeUser32({CLOUD_ID: dword(0), HISTORY_ID: dword(1)})
    privacy = make_reader(user32).read()

    assert privacy.cloud_allowed is False
    assert decide_capture(privacy) is CapturePolicy.ALLOW


@pytest.mark.parametrize("payload", [b"", b"\x01", b"\x00" * 3, b"\x00" * 8, b"\x00" * 2])
def test_malformed_history_payload_fails_closed(payload: bytes) -> None:
    user32 = FakeUser32({HISTORY_ID: payload})
    privacy = make_reader(user32).read()

    assert privacy.history_allowed is None
    assert privacy.history_invalid is True
    assert decide_capture(privacy) is CapturePolicy.BLOCK_INVALID


def test_clipboard_is_opened_and_closed_once() -> None:
    user32 = FakeUser32({HISTORY_ID: dword(1)})

    make_reader(user32).read()

    assert user32.open_calls == 1
    assert user32.close_calls == 1


def test_clipboard_open_retries_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("clipnest.core.clipboard_flags.OPEN_RETRY_SECONDS", 0.0)
    user32 = FakeUser32({HISTORY_ID: dword(1)}, open_failures=2)

    privacy = make_reader(user32).read()

    assert privacy.history_allowed is True
    assert user32.open_calls == 3


def test_clipboard_stays_locked_raises_and_does_not_close(monkeypatch) -> None:
    monkeypatch.setattr("clipnest.core.clipboard_flags.OPEN_RETRY_SECONDS", 0.0)
    user32 = FakeUser32(open_failures=99)
    reader = make_reader(user32)

    with pytest.raises(ClipboardFlagsError):
        reader.read()

    assert user32.open_calls == 5
    assert user32.close_calls == 0


def test_marker_memory_is_unlocked_after_reading() -> None:
    user32 = FakeUser32({HISTORY_ID: dword(1), CLOUD_ID: dword(1)})
    kernel32 = FakeKernel32(user32)
    make_reader(user32, kernel32).read()

    assert kernel32.locked == kernel32.unlocked
    assert len(kernel32.locked) == 2


def test_lock_failure_raises_and_still_closes_clipboard() -> None:
    user32 = FakeUser32({HISTORY_ID: dword(1)})
    reader = make_reader(user32, FakeKernel32(user32, fail_lock=True))

    with pytest.raises(ClipboardFlagsError):
        reader.read()

    assert user32.close_calls == 1


def test_format_registration_failure_raises_before_opening() -> None:
    user32 = FakeUser32(bad_formats={EXCLUDE_FORMAT_NAME})
    reader = make_reader(user32)

    with pytest.raises(ClipboardFlagsError):
        reader.read()

    assert user32.open_calls == 0


def test_formats_are_registered_only_once() -> None:
    user32 = FakeUser32({HISTORY_ID: dword(1)})
    reader = make_reader(user32)

    reader.read()
    reader.read()

    assert user32.register_calls == [
        EXCLUDE_FORMAT_NAME,
        HISTORY_FORMAT_NAME,
        CLOUD_FORMAT_NAME,
    ]


def test_reader_reports_support_once_apis_are_injected() -> None:
    reader = make_reader(FakeUser32())

    assert reader.is_supported is True


def test_native_modules_are_not_loaded_without_windows(monkeypatch) -> None:
    monkeypatch.setattr("clipnest.core.clipboard_flags.IS_WINDOWS", False)
    reader = WindowsClipboardFlags()

    assert reader.is_supported is False
    with pytest.raises(ClipboardFlagsError):
        reader.read()
