"""Tests for the at-rest protector: the DPAPI wrapper and the inert fallback.

The wrapper is exercised against a recording double for ``crypt32``/``kernel32``
so argument marshalling and failure handling are covered everywhere, plus one
real DPAPI round trip on Windows (DPAPI is a pure crypto call: it touches no
clipboard and no clip data).
"""

from __future__ import annotations

import ctypes

import pytest

from clipnest.core.protection import (
    BLOB_DESCRIPTION,
    CRYPTPROTECT_UI_FORBIDDEN,
    ENTROPY,
    IS_WINDOWS,
    DpapiTextProtector,
    PlaintextTextProtector,
    ProtectionError,
    default_text_protector,
)

CANARY = "dpapi-wrapper-canary-5f3"


class FakeKernel32:
    """Records ``LocalFree`` calls made for DPAPI output buffers."""

    def __init__(self) -> None:
        self.freed = 0

    def LocalFree(self, pointer) -> int:  # noqa: N802 - mirrors the Win32 name
        self.freed += 1
        return 0


class FakeCrypt32:
    """Reverses its input, recording exactly what the wrapper passed in."""

    def __init__(self, succeed: bool = True, payload_override: bytes | None = None):
        self.succeed = succeed
        self.payload_override = payload_override
        self.calls: list[dict[str, object]] = []
        self._buffers: list[ctypes.Array] = []

    def CryptProtectData(  # noqa: N802 - mirrors the Win32 name
        self, in_ptr, description, entropy_ptr, reserved, prompt, flags, out_ptr
    ) -> int:
        return self._call("protect", in_ptr, description, entropy_ptr, flags, out_ptr)

    def CryptUnprotectData(  # noqa: N802 - mirrors the Win32 name
        self, in_ptr, description, entropy_ptr, reserved, prompt, flags, out_ptr
    ) -> int:
        return self._call("unprotect", in_ptr, description, entropy_ptr, flags, out_ptr)

    def _call(self, direction, in_ptr, description, entropy_ptr, flags, out_ptr) -> int:
        source = in_ptr.contents
        entropy = entropy_ptr.contents
        self.calls.append(
            {
                "direction": direction,
                "description": description,
                "flags": flags,
                "data": ctypes.string_at(source.pbData, source.cbData),
                "entropy": ctypes.string_at(entropy.pbData, entropy.cbData),
            }
        )
        if not self.succeed:
            return 0
        if self.payload_override is not None:
            payload = self.payload_override
        else:
            # A plain reversal keeps the round trip symmetric for both calls.
            payload = bytes(reversed(ctypes.string_at(source.pbData, source.cbData)))
        buffer = ctypes.create_string_buffer(payload, max(len(payload), 1))
        self._buffers.append(buffer)
        out_ptr.contents.cbData = len(payload)
        out_ptr.contents.pbData = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
        return 1


def test_wrapper_passes_description_entropy_and_flags() -> None:
    crypt32 = FakeCrypt32()
    kernel32 = FakeKernel32()
    protector = DpapiTextProtector(crypt32, kernel32)

    protector.protect(CANARY)

    call = crypt32.calls[0]
    assert call["description"] == BLOB_DESCRIPTION
    assert call["flags"] == CRYPTPROTECT_UI_FORBIDDEN
    assert call["entropy"] == ENTROPY
    assert call["data"] == CANARY.encode("utf-8")
    # The output buffer DPAPI allocated is released again.
    assert kernel32.freed == 1


def test_wrapper_round_trips_through_a_recording_double() -> None:
    crypt32 = FakeCrypt32()
    protector = DpapiTextProtector(crypt32, FakeKernel32())

    blob = protector.protect(CANARY)
    restored = protector.unprotect(blob)

    assert restored == CANARY
    assert CANARY.encode("utf-8") not in blob
    assert [call["direction"] for call in crypt32.calls] == ["protect", "unprotect"]


def test_encrypt_failure_raises_without_the_snippet() -> None:
    protector = DpapiTextProtector(FakeCrypt32(succeed=False), FakeKernel32())

    with pytest.raises(ProtectionError) as excinfo:
        protector.protect("this-value-must-not-appear")

    assert "this-value-must-not-appear" not in str(excinfo.value)


def test_decrypt_failure_raises_without_the_snippet() -> None:
    protector = DpapiTextProtector(FakeCrypt32(succeed=False), FakeKernel32())

    with pytest.raises(ProtectionError) as excinfo:
        protector.unprotect(b"not-a-dpapi-blob")

    assert "not-a-dpapi-blob" not in str(excinfo.value)


def test_decrypted_bytes_that_are_not_text_are_rejected() -> None:
    crypt32 = FakeCrypt32(payload_override=b"\xff\xfe\x00\x01")
    protector = DpapiTextProtector(crypt32, FakeKernel32())

    with pytest.raises(ProtectionError):
        protector.unprotect(b"anything")


def test_plaintext_protector_is_honest_about_not_encrypting() -> None:
    protector = PlaintextTextProtector()

    assert protector.is_encrypted is False
    assert protector.protect("plain") == b"plain"
    assert protector.unprotect(b"plain") == "plain"


def test_plaintext_protector_rejects_bytes_that_are_not_utf8() -> None:
    with pytest.raises(ProtectionError):
        PlaintextTextProtector().unprotect(b"\xff\xfe")


def test_default_protector_matches_the_platform() -> None:
    protector = default_text_protector()

    # Constructing the DPAPI protector loads no DLL, so this stays offline.
    assert protector.is_encrypted is IS_WINDOWS
    assert protector.name == ("dpapi" if IS_WINDOWS else "plaintext")


def test_unloadable_dpapi_raises_protection_error(monkeypatch) -> None:
    """A Windows image without crypt32 must fail as a protection error."""
    import clipnest.core.protection as protection

    def missing_dll(*args, **kwargs):
        raise OSError("the specified module could not be found")

    monkeypatch.setattr(protection, "IS_WINDOWS", True)
    monkeypatch.setattr(protection.ctypes, "WinDLL", missing_dll)
    protector = DpapiTextProtector()

    with pytest.raises(ProtectionError) as excinfo:
        protector.protect("no-crypt32-canary-91b")

    assert "no-crypt32-canary-91b" not in str(excinfo.value)


def test_repository_refuses_to_start_when_dpapi_is_unavailable(
    tmp_path, monkeypatch
) -> None:
    """The failure reaches the user as ``StorageError``, not as an OSError."""
    import clipnest.core.protection as protection
    from clipnest.core.storage import ClipboardRepository, StorageError

    def missing_dll(*args, **kwargs):
        raise OSError("the specified module could not be found")

    monkeypatch.setattr(protection, "IS_WINDOWS", True)
    monkeypatch.setattr(protection.ctypes, "WinDLL", missing_dll)

    with pytest.raises(StorageError) as excinfo:
        ClipboardRepository(tmp_path / "no-dpapi.db", protector=DpapiTextProtector())

    assert "no-crypt32-canary-91b" not in str(excinfo.value)


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows DPAPI is Windows-only")
def test_real_dpapi_round_trip_and_tamper_detection() -> None:
    protector = DpapiTextProtector()

    blob = protector.protect(CANARY)

    assert CANARY.encode("utf-8") not in blob
    assert protector.unprotect(blob) == CANARY

    middle = len(blob) // 2
    tampered = bytes([blob[middle] ^ 0xFF]).join([blob[:middle], blob[middle + 1 :]])
    with pytest.raises(ProtectionError):
        protector.unprotect(tampered)
