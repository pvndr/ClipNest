"""Tests for sensitive-content detection.

Every value here is synthetic: prefixes are padded with canary letters so no
real credential shape is used, and the assertions check that nothing but the
category can ever escape the detector.
"""

from __future__ import annotations

import pytest

from clipnest.core.sensitive import (
    MAX_SCAN_LENGTH,
    SensitiveFinding,
    SensitiveKind,
    detect,
)

PRIVATE_KEY = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEcanarycanarycanarycanarycanarycanary\n"
    "-----END RSA PRIVATE KEY-----"
)
OPENSSH_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ\n"
    "-----END OPENSSH PRIVATE KEY-----"
)

API_KEYS = (
    "ghp_" + "canary" * 6,  # GitHub
    "github_pat_" + "canary" * 4,
    "sk-proj-" + "canary" * 4,  # OpenAI-style
    "xoxb-" + "canary-1234",  # Slack
    "AKIA" + "CANARYCANARY1234",  # AWS access key id
    "AIza" + "Canary0123456789" * 2 + "abc",  # Google
    "glpat-" + "canary" * 4,  # GitLab
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjYW5hcnkifQ.abcdefghijkl",  # JWT
)

CREDENTIALS = (
    "password = Canary9value",
    "DB_PASSWORD: 's3cr3t-Canary'",
    "client_secret=abc123canary",
    "token: abcdef123456",
    "access_key = 7f3c9d2e1b",
    "api_key: 9f8e7d6c5b4a",
    "pwd=Hunter2Canary",
)

CARD_NUMBERS = ("4111111111111111", "5555 5555 5555 4444", "378282246310005")

ONE_TIME_CODES = (
    "Your verification code is 481920",
    "OTP: 4819",
    "2FA code 123456",
    "Two-factor passcode: 90210",
)


# ----------------------------------------------------------------- categories


@pytest.mark.parametrize("text", [PRIVATE_KEY, OPENSSH_KEY])
def test_private_key_blocks(text: str) -> None:
    assert detect(text) == SensitiveFinding(SensitiveKind.PRIVATE_KEY)


@pytest.mark.parametrize("text", API_KEYS)
def test_provider_keys_are_detected(text: str) -> None:
    assert detect(text) == SensitiveFinding(SensitiveKind.API_KEY)


@pytest.mark.parametrize("text", CREDENTIALS)
def test_credential_assignments_are_detected(text: str) -> None:
    assert detect(text) == SensitiveFinding(SensitiveKind.CREDENTIAL)


@pytest.mark.parametrize("text", CARD_NUMBERS)
def test_card_numbers_are_detected(text: str) -> None:
    assert detect(text) == SensitiveFinding(SensitiveKind.CARD_NUMBER)


@pytest.mark.parametrize("text", ONE_TIME_CODES)
def test_one_time_codes_are_detected(text: str) -> None:
    assert detect(text) == SensitiveFinding(SensitiveKind.ONE_TIME_CODE)


# --------------------------------------------------------------------- safe


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n\t ",
        "The quick brown fox jumps over the lazy dog.",
        "def main():\n    return 0\n",
        "SELECT id, name FROM entries WHERE pinned = 0;",
        "Call me on 555-1234 when you land.",
        "Order 123456 shipped yesterday.",
        "Version 1.2.3 was released on 2026-10-27.",
        "Status code 5000 means the upstream service is down.",
        "Bearer tokens expire in 3600 seconds.",
        "The password reset email never arrived.",
        "Set the token count to 512 before running the job.",
        "My password is hunter2 and I know it is weak.",
        "4111 1111 1111 1112",  # fails the Luhn check
        "1234 5678 9012 3456",  # fails the issuer-prefix check
        "Use the code 12 to unlock.",  # too short to be a code
    ],
)
def test_ordinary_text_is_not_flagged(text: str) -> None:
    assert detect(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "password: ${DB_PASSWORD}",
        "password = %DB_PASSWORD%",
        "token: $CLIPNEST_TOKEN",
        "client_secret: {{ client_secret }}",
        "api_key: <your-api-key>",
        "secret = ********",
        "pwd: xxxxxxxx",
        "password: changeme",
        "token: REDACTED",
        "API_KEY=os.environ['API_KEY']",
        "secret: getenv('APP_SECRET')",
        "access_key: TODO",
    ],
)
def test_placeholders_are_not_flagged(text: str) -> None:
    assert detect(text) is None


def test_weak_otp_context_requires_six_digits() -> None:
    assert detect("error code 4819") is None
    assert detect("error code 481920") is not None


def test_strong_otp_context_accepts_four_digits() -> None:
    assert detect("your one-time code is 4819") is not None


# ------------------------------------------------------------ safe results


def test_result_never_carries_the_matched_value() -> None:
    canary = "ghp_" + "canary" * 6

    finding = detect(canary)

    assert finding is not None
    assert canary not in repr(finding)
    assert canary not in str(finding)
    assert finding == SensitiveFinding(SensitiveKind.API_KEY)


# --------------------------------------------------------------- boundaries


def test_multiline_private_key_is_detected() -> None:
    text = "notes:\n" + PRIVATE_KEY + "\nmore notes"

    assert detect(text) == SensitiveFinding(SensitiveKind.PRIVATE_KEY)


def test_truncated_private_key_header_is_not_detected() -> None:
    assert detect("-----BEGIN RSA PRIVATE") is None


def test_oversized_input_is_bounded() -> None:
    padding = "ordinary prose. " * 4_000
    text = padding + API_KEYS[0]

    assert len(text) > MAX_SCAN_LENGTH
    # The scan stops at MAX_SCAN_LENGTH, which is documented behaviour.
    assert detect(text) is None


def test_secret_within_the_scan_window_is_detected() -> None:
    text = API_KEYS[0] + " " + "x" * (MAX_SCAN_LENGTH * 2)

    assert detect(text) == SensitiveFinding(SensitiveKind.API_KEY)
