"""At-rest protection for stored clipboard text.

The database must never contain a snippet as readable text. Every value written
to the ``cipher`` column goes through a :class:`TextProtector` first, and every
value read back is unprotected before it reaches the UI.

Windows uses DPAPI (``CryptProtectData``) through ``ctypes``: the key is derived
from the current Windows account and never leaves the operating system, no
password is chosen by ClipNest, and the blob carries an integrity check, so a
tampered row fails to decrypt instead of returning corrupted text. There is no
separate key to lose, which is also the honest limit of this design: a history
belongs to the Windows profile that created it, and it cannot be recovered on
another account or machine.

``PlaintextTextProtector`` exists for two reasons: it is the inert default that
keeps the repository usable in tests without touching the developer's DPAPI
state, and it is what a non-Windows run falls back to (reported as
``is_encrypted = False`` rather than pretending). The shipped application is
Windows-only and always injects the DPAPI protector from its composition root.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Protocol

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

#: Optional entropy mixed into every DPAPI blob, so a blob from another
#: application that also uses DPAPI cannot be substituted for a snippet.
ENTROPY = b"ClipNest/at-rest/v1"
BLOB_DESCRIPTION = "ClipNest clipboard entry"

#: ``CryptProtectData`` flag: never show a UI prompt (this runs in the app).
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class ProtectionError(RuntimeError):
    """Raised when stored text cannot be protected or unprotected."""


class TextProtector(Protocol):
    """Protects and restores one stored snippet."""

    name: str
    is_encrypted: bool

    def protect(self, text: str) -> bytes: ...

    def unprotect(self, blob: bytes) -> str: ...


class PlaintextTextProtector:
    """Identity protector: UTF-8 in the file, no encryption at all.

    Used when DPAPI is unavailable and as the inert default in tests. It is
    explicit about that: ``is_encrypted`` is ``False``.
    """

    name = "plaintext"
    is_encrypted = False

    def protect(self, text: str) -> bytes:
        return text.encode("utf-8")

    def unprotect(self, blob: bytes) -> str:
        try:
            return bytes(blob).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtectionError("Stored snippet is not valid UTF-8") from exc


class DATA_BLOB(ctypes.Structure):
    """The DPAPI input/output buffer (``windef.h``)."""

    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _make_blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    """Wrap ``data`` in a ``DATA_BLOB``; the second value keeps it alive.

    ``ctypes.pointer`` is used instead of ``ctypes.byref`` so the blob can be
    dereferenced by test doubles without a real DLL call.
    """
    buffer = ctypes.create_string_buffer(bytes(data), max(len(data), 1))
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


class DpapiTextProtector:
    """Windows DPAPI protector scoped to the current user profile."""

    name = "dpapi"
    is_encrypted = True

    def __init__(self, crypt32=None, kernel32=None) -> None:
        # Both are injected by tests; the real DLLs load on first use so
        # importing this module never touches DPAPI.
        self._crypt32 = crypt32
        self._kernel32 = kernel32

    def _libs(self):
        if self._crypt32 is None or self._kernel32 is None:
            if not IS_WINDOWS:
                raise ProtectionError("Windows DPAPI is not available here")
            try:
                self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
                self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            except (OSError, AttributeError, ValueError) as exc:
                # A Windows image without crypt32 (a stripped container, a
                # broken install) must fail as a reportable protection error,
                # not as an OSError escaping through the repository.
                raise ProtectionError(
                    "Windows DPAPI could not be loaded on this system"
                ) from exc
        return self._crypt32, self._kernel32

    def protect(self, text: str) -> bytes:
        """Encrypt ``text`` for this Windows account."""
        data = text.encode("utf-8")
        crypt32, _ = self._libs()
        # The buffers stay referenced for the duration of the call.
        in_blob, _in_buffer = _make_blob(data)
        entropy_blob, _entropy_buffer = _make_blob(ENTROPY)
        out_blob = DATA_BLOB()
        ok = crypt32.CryptProtectData(
            ctypes.pointer(in_blob),
            BLOB_DESCRIPTION,
            ctypes.pointer(entropy_blob),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.pointer(out_blob),
        )
        if not ok:
            raise ProtectionError(
                "Windows DPAPI could not encrypt a snippet "
                f"(error {ctypes.get_last_error()})"
            )
        return self._take_output(out_blob)

    def unprotect(self, blob: bytes) -> str:
        """Decrypt a blob written by :meth:`protect` for this account."""
        crypt32, _ = self._libs()
        in_blob, _in_buffer = _make_blob(bytes(blob))
        entropy_blob, _entropy_buffer = _make_blob(ENTROPY)
        out_blob = DATA_BLOB()
        ok = crypt32.CryptUnprotectData(
            ctypes.pointer(in_blob),
            None,
            ctypes.pointer(entropy_blob),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.pointer(out_blob),
        )
        if not ok:
            raise ProtectionError(
                "Windows DPAPI could not decrypt a stored snippet "
                f"(error {ctypes.get_last_error()})"
            )
        raw = self._take_output(out_blob)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtectionError("Decrypted snippet is not text") from exc

    def _take_output(self, out_blob: DATA_BLOB) -> bytes:
        """Copy out a DPAPI output buffer and free it with ``LocalFree``."""
        _, kernel32 = self._libs()
        try:
            if not out_blob.pbData:
                return b""
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            if out_blob.pbData:
                kernel32.LocalFree(out_blob.pbData)


def default_text_protector() -> TextProtector:
    """Return the protector the application should use on this platform."""
    if IS_WINDOWS:
        return DpapiTextProtector()
    logger.warning(
        "Windows DPAPI is unavailable on this platform; snippets are stored "
        "unencrypted"
    )
    return PlaintextTextProtector()
