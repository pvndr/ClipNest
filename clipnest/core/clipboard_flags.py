"""Windows clipboard privacy markers, read through documented Win32 APIs.

Windows lets a source application tell clipboard managers how its content may
be handled. Three registered formats matter here:

``ExcludeClipboardContentFromMonitorProcessing``
    Presence-based marker. When a source application sets this format,
    monitoring applications must not process the clipboard at all.
``CanIncludeInClipboardHistory``
    A serialized ``DWORD``. ``0`` means "keep this out of the local clipboard
    history"; ``1`` explicitly allows it. A non-zero but unparsable payload is
    treated as invalid.
``CanUploadToCloudClipboard``
    A serialized ``DWORD`` about cloud clipboard sync. ClipNest never uploads
    anything, so this value is reported for diagnostics and never decides
    whether content is captured.

The module is deliberately isolated: it does not import Qt, does not know the
clipboard service, and never returns the clipboard text. It only opens the
Win32 clipboard, reads those three formats, and closes it again. Every handle
is released on the way out, and every native failure becomes a
:class:`ClipboardFlagsError` so the caller can apply its documented policy
instead of assuming the content is safe.

The decision table lives in :func:`read_capture_policy` so it can be reviewed
and tested without a clipboard:

===================  ==========================================  =============
Marker state          Meaning                                    Policy
===================  ==========================================  =============
(exclusion present)  Source app excluded monitoring              block
history == 0         Source app excluded local history           block
history invalid      Format present, payload unusable            block (closed)
history absent/1     No objection / explicit permission          allow
read failure         Clipboard locked or a Win32 call failed     block (closed)
platform unsupported Formats do not exist on this platform      allow
===================  ==========================================  =============
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

EXCLUDE_FORMAT_NAME = "ExcludeClipboardContentFromMonitorProcessing"
HISTORY_FORMAT_NAME = "CanIncludeInClipboardHistory"
CLOUD_FORMAT_NAME = "CanUploadToCloudClipboard"

DWORD_SIZE = 4
OPEN_ATTEMPTS = 5
OPEN_RETRY_SECONDS = 0.01


class ClipboardFlagsError(RuntimeError):
    """Raised when the clipboard privacy markers cannot be read reliably.

    The message never contains clipboard content: it names the failing Win32
    call only.
    """


@dataclass(frozen=True)
class ClipboardPrivacy:
    """What the source application said about the current clipboard content."""

    excluded: bool = False
    """``ExcludeClipboardContentFromMonitorProcessing`` was present."""

    history_allowed: bool | None = None
    """``CanIncludeInClipboardHistory`` value, or ``None`` when absent."""

    cloud_allowed: bool | None = None
    """``CanUploadToCloudClipboard`` value. Diagnostic only."""

    history_invalid: bool = False
    """The history format was present but its payload was not a ``DWORD``."""


class CapturePolicy(Enum):
    """The documented decision for one clipboard change event."""

    ALLOW = "allow"
    BLOCK_MARKER = "marker"
    BLOCK_HISTORY = "history"
    BLOCK_INVALID = "invalid"
    BLOCK_UNREADABLE = "unreadable"


def decide_capture(privacy: ClipboardPrivacy) -> CapturePolicy:
    """Map marker state to a capture decision.

    Fails closed: an exclusion marker, an explicit ``0`` history flag, or an
    unparsable history payload all block capture. Only "nothing was said" or
    an explicit ``1`` allow it.
    """
    if privacy.excluded:
        return CapturePolicy.BLOCK_MARKER
    if privacy.history_invalid:
        return CapturePolicy.BLOCK_INVALID
    if privacy.history_allowed is False:
        return CapturePolicy.BLOCK_HISTORY
    return CapturePolicy.ALLOW


class ClipboardFlagsProvider(Protocol):
    """Reads the platform's clipboard privacy markers."""

    @property
    def is_supported(self) -> bool:
        """Whether this platform has these clipboard formats at all."""

    def read(self) -> ClipboardPrivacy:
        """Return the current marker state, or raise ``ClipboardFlagsError``."""


class UnsupportedClipboardFlags:
    """Provider for platforms without these clipboard privacy formats.

    The formats are a Windows shell feature, and ClipNest only ships for
    Windows: on any other platform "no marker" is the truthful answer rather
    than an unknown one.
    """

    is_supported = False

    def read(self) -> ClipboardPrivacy:
        return ClipboardPrivacy()


class WindowsClipboardFlags:
    """Reads the three registered formats from the Win32 clipboard.

    The APIs are resolved lazily and cached, so importing this module on a
    non-Windows interpreter is harmless and an incomplete Windows API surface
    degrades into "not supported" instead of an import-time crash.
    """

    def __init__(self) -> None:
        self._user32 = None
        self._kernel32 = None
        self._load_failed = False
        self._formats: tuple[int, int, int] | None = None

    @property
    def is_supported(self) -> bool:
        """Whether the Win32 clipboard APIs are usable on this interpreter."""
        return IS_WINDOWS and self._load() is not None

    def read(self) -> ClipboardPrivacy:
        """Open the clipboard, read the markers, and close it again.

        Retries a few times because another process may hold the clipboard for
        a few milliseconds; a lasting failure raises
        :class:`ClipboardFlagsError` so the caller can fail closed.
        """
        api = self._load()
        if api is None:
            raise ClipboardFlagsError(
                "The Windows clipboard APIs are not available on this platform"
            )
        user32 = api
        exclude_id, history_id, cloud_id = self._register_formats(user32)

        if not self._open(user32):
            raise ClipboardFlagsError(
                "The clipboard is locked by another application"
            )
        try:
            excluded = self._has_payload(user32, exclude_id)
            history_allowed, history_invalid = self._read_dword(user32, history_id)
            cloud_allowed, _ = self._read_dword(user32, cloud_id)
        finally:
            # CloseClipboard only fails when the clipboard is not open; the
            # handle is already gone at that point.
            user32.CloseClipboard()

        return ClipboardPrivacy(
            excluded=excluded,
            history_allowed=history_allowed,
            cloud_allowed=cloud_allowed,
            history_invalid=history_invalid,
        )

    # -------------------------------------------------------------- internals

    def _load(self):
        """Resolve ``user32`` with declared signatures, or ``None``."""
        if self._user32 is not None:
            return self._user32
        if self._load_failed or not IS_WINDOWS:
            return None
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except (OSError, AttributeError, ValueError):
            logger.warning("Windows clipboard APIs could not be loaded")
            self._load_failed = True
            return None

        user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterClipboardFormatW.restype = wintypes.UINT
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalSize.argtypes = [wintypes.HANDLE]
        kernel32.GlobalSize.restype = ctypes.c_size_t

        self._user32 = user32
        self._kernel32 = kernel32
        return user32

    def _register_formats(self, user32) -> tuple[int, int, int]:
        """Resolve the three format ids once per process."""
        if self._formats is not None:
            return self._formats
        ids = []
        for name in (EXCLUDE_FORMAT_NAME, HISTORY_FORMAT_NAME, CLOUD_FORMAT_NAME):
            format_id = int(user32.RegisterClipboardFormatW(name))
            if format_id == 0:
                raise ClipboardFlagsError(
                    "A clipboard privacy format could not be registered"
                )
            ids.append(format_id)
        self._formats = (ids[0], ids[1], ids[2])
        return self._formats

    def _open(self, user32) -> bool:
        """Open the clipboard with a short retry loop for contention."""
        for attempt in range(OPEN_ATTEMPTS):
            if user32.OpenClipboard(None):
                return True
            if attempt + 1 < OPEN_ATTEMPTS:
                time.sleep(OPEN_RETRY_SECONDS)
        logger.debug("Clipboard stayed locked for %d attempts", OPEN_ATTEMPTS)
        return False

    def _has_payload(self, user32, format_id: int) -> bool:
        """Whether ``format_id`` is present in the open clipboard."""
        return bool(user32.GetClipboardData(format_id))

    def _read_dword(self, user32, format_id: int) -> tuple[bool | None, bool]:
        """Read a serialized ``DWORD`` marker.

        Returns ``(value, invalid)``: ``(None, False)`` when the format is
        absent, ``(None, True)`` when the payload is not exactly one ``DWORD``,
        otherwise the boolean value.
        """
        handle = user32.GetClipboardData(format_id)
        if not handle:
            return None, False

        size = int(self._kernel32.GlobalSize(handle))
        if size != DWORD_SIZE:
            return None, True

        pointer = self._kernel32.GlobalLock(handle)
        if not pointer:
            raise ClipboardFlagsError("Clipboard marker memory could not be locked")
        try:
            import ctypes

            raw = ctypes.string_at(pointer, DWORD_SIZE)
        finally:
            self._kernel32.GlobalUnlock(handle)
        return int.from_bytes(raw, "little") != 0, False


def default_flags_provider() -> ClipboardFlagsProvider:
    """Return the provider for this platform.

    Only the composition root calls this: the clipboard service receives an
    explicit provider so tests never reach the native clipboard.
    """
    if IS_WINDOWS:
        return WindowsClipboardFlags()
    return UnsupportedClipboardFlags()


def read_capture_policy(
    provider: ClipboardFlagsProvider,
) -> CapturePolicy:
    """Evaluate ``provider`` and return the documented capture decision.

    Unreadable markers block capture: an unknown state is never reported as
    safe, and a skipped capture loses nothing that was actually stored.
    """
    if not provider.is_supported:
        return CapturePolicy.ALLOW
    try:
        privacy = provider.read()
    except ClipboardFlagsError:
        logger.debug("Clipboard privacy markers could not be read")
        return CapturePolicy.BLOCK_UNREADABLE
    except Exception:  # a native wrapper must never break capture outright
        logger.debug("Clipboard privacy markers raised unexpectedly")
        return CapturePolicy.BLOCK_UNREADABLE
    return decide_capture(privacy)


def _main() -> int:
    """Print the current marker state only - never the clipboard content."""
    provider = default_flags_provider()
    if not provider.is_supported:
        print(f"Clipboard privacy markers: unsupported on platform {sys.platform!r}")
        return 0
    try:
        privacy = provider.read()
    except ClipboardFlagsError as exc:
        print(f"Privacy markers unreadable: {exc}")
        return 1
    print(f"excluded={privacy.excluded}")
    print(f"history_allowed={privacy.history_allowed}")
    print(f"cloud_allowed={privacy.cloud_allowed}")
    print(f"history_invalid={privacy.history_invalid}")
    print(f"policy={read_capture_policy(provider).value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
