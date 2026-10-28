"""Sensitive-content detection for clipboard capture.

Pure logic: no Qt, no database, no Win32. :func:`detect` returns the *category*
of a finding and nothing else, so no matched value, line, or token prefix can
leak into a log message, notification, or exception.

The rules are deliberately conservative - a false negative is a snippet the
user deleted, a false positive breaks ordinary work - so:

* provider prefixes must match their documented shape exactly;
* a credential assignment must have a key-like name, a separator, and a value
  that is not an environment reference or a template placeholder;
* a code is only an OTP when a contextual word sits next to it;
* a card candidate must pass a length check, a Luhn check, *and* a known
  issuer prefix.

Only the first :data:`MAX_SCAN_LENGTH` characters are examined, so pathological
input cannot turn one clipboard event into unbounded work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

MAX_SCAN_LENGTH = 20_000


class SensitiveKind(Enum):
    """What kind of sensitive content was recognised."""

    PRIVATE_KEY = "private_key"
    API_KEY = "api_key"
    CREDENTIAL = "credential"
    CARD_NUMBER = "card_number"
    ONE_TIME_CODE = "one_time_code"


@dataclass(frozen=True)
class SensitiveFinding:
    """A detection result that is safe to log and display."""

    kind: SensitiveKind


# --------------------------------------------------------------- provider keys

_PROVIDER_PATTERNS = (
    # PEM / OpenSSH private-key headers.
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),
    # GitHub: ghp_, gho_, ghu_, ghs_, ghr_, github_pat_
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    # OpenAI-style: sk-..., sk-proj-..., sk-svcacct-...
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    # Slack: xoxb-, xoxp-, xoxa-, xoxs-, xoxr-
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b"),
    # AWS access key ids.
    re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA|AIPA)[A-Z0-9]{16}\b"),
    # Google API keys.
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    # GitLab personal/project/group access tokens.
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    # JWT-like: three base64url segments, header starting with {"alg".
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)

_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b[A-Za-z0-9_.-]*(?:password|passwd|pwd|secret|token|api[_-]?key"
    r"|client[_-]?secret|access[_-]?key)\b\s*(?:[:=]|=>|:=)\s*"
    r"(?P<value>\"[^\"\n]{6,}\"|'[^'\n]{6,}'|[^\s\"'`,;]{6,})"
)

_ENV_REFERENCE = re.compile(
    r"(?i)(?:\$\{|\$[a-z_]|%[a-z_][a-z0-9_]*%|os\.environ|os\.getenv|getenv\(|"
    r"process\.env|env::|sys\.argv)"
)

_PLACEHOLDER_VALUES = (
    re.compile(r"^\$\{.*\}$"),
    re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*$"),
    re.compile(r"^%[A-Za-z_][A-Za-z0-9_]*%$"),
    re.compile(r"^\{\{.*\}\}$"),
    re.compile(r"^<[^<>]*>$"),
    re.compile(r"^\[[^\[\]]*\]$"),
    re.compile(r"^\*+$"),
    re.compile(r"^x+$", re.IGNORECASE),
    re.compile(r"^\.+$"),
    re.compile(r"^-+$"),
)

_PLACEHOLDER_WORDS = re.compile(
    r"(?i)^(?:"
    r"redacted|removed|hidden|masked|"
    r"change[_-]?me|changeme|replace[_-]?me|your[_-].*|"
    r"placeholder|example|sample|dummy|fake|test|test[_-].*|"
    r"todo|fixme|none|null|nil|undefined|not[_-]?set|insert[_-].*"
    r")$"
)

# Contextual words that turn a short number into a one-time code. A bare number
# is never treated as an OTP, and the generic word "code" only counts for a
# six-or-more-digit number so "status code 5000" stays ordinary text.
_STRONG_OTP_CONTEXT = re.compile(
    r"(?i)\b(?:otp|one[-\s]?time|2fa|two[-\s]?factor|mfa|verification|passcode|"
    r"authenticator)\b"
)
_WEAK_OTP_CONTEXT = re.compile(
    r"(?i)\b(?:verify|code|security[-\s]?code|auth(?:entication)?[-\s]?code)\b"
)
_NUMBER_TOKEN = re.compile(r"\b\d{4,8}\b")
_OTP_CONTEXT_WINDOW = 40
_WEAK_OTP_MIN_DIGITS = 6

_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")

_CARD_ISSUER_PREFIXES = (5018, 5020, 5038, 5893, 6304, 6759, 6761, 6762, 6763)


def detect(text: str) -> SensitiveFinding | None:
    """Return the first sensitive category found in ``text``, or ``None``.

    The result never contains the matched substring.
    """
    if not text:
        return None
    sample = text[:MAX_SCAN_LENGTH]

    for pattern in _PROVIDER_PATTERNS:
        if pattern.search(sample):
            kind = (
                SensitiveKind.PRIVATE_KEY
                if pattern.pattern.startswith("-----BEGIN")
                else SensitiveKind.API_KEY
            )
            return SensitiveFinding(kind)

    for match in _CREDENTIAL_PATTERN.finditer(sample):
        value = match.group("value").strip("\"'")
        if _looks_like_secret_value(value) and not _is_placeholder(value):
            return SensitiveFinding(SensitiveKind.CREDENTIAL)

    if _looks_like_card(sample):
        return SensitiveFinding(SensitiveKind.CARD_NUMBER)

    if _looks_like_one_time_code(sample):
        return SensitiveFinding(SensitiveKind.ONE_TIME_CODE)

    return None


def _looks_like_secret_value(value: str) -> bool:
    """Whether the right-hand side of an assignment looks like a secret.

    A word such as ``required`` after ``password:`` is prose, not a credential.
    Requiring either a digit, a symbol, mixed case, or real length keeps those
    out while still catching generated passwords and passphrases.
    """
    if len(value) < 8:
        return False
    if any(character.isdigit() for character in value):
        return True
    if any(not character.isalnum() for character in value):
        return True
    if any(character.islower() for character in value) and any(
        character.isupper() for character in value
    ):
        return True
    return len(value) >= 16


def _is_placeholder(value: str) -> bool:
    """Whether ``value`` is an obvious reference or template placeholder."""
    if not value:
        return True
    if _ENV_REFERENCE.search(value):
        return True
    if _PLACEHOLDER_WORDS.match(value):
        return True
    return any(pattern.match(value) for pattern in _PLACEHOLDER_VALUES)


def _looks_like_card(text: str) -> bool:
    for match in _CARD_CANDIDATE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if not 13 <= len(digits) <= 19:
            continue
        if not _has_known_issuer_prefix(digits):
            continue
        if _luhn_valid(digits):
            return True
    return False


def _looks_like_one_time_code(text: str) -> bool:
    for match in _NUMBER_TOKEN.finditer(text):
        digits = match.group(0)
        start, end = match.span()
        window_start = max(0, start - _OTP_CONTEXT_WINDOW)
        window_end = min(len(text), end + _OTP_CONTEXT_WINDOW)
        window = text[window_start:window_end]
        if _STRONG_OTP_CONTEXT.search(window):
            return True
        if len(digits) >= _WEAK_OTP_MIN_DIGITS and _WEAK_OTP_CONTEXT.search(window):
            return True
    return False


def _has_known_issuer_prefix(digits: str) -> bool:
    """Reject plausible arbitrary numbers before the Luhn check."""
    if digits[0] == "4":  # Visa
        return True
    first_two = int(digits[:2])
    first_three = int(digits[:3])
    first_four = int(digits[:4])
    if 51 <= first_two <= 55 or 2221 <= first_four <= 2720:  # Mastercard
        return True
    if first_two in (34, 37):  # American Express
        return True
    if first_four == 6011 or first_two == 65 or 644 <= first_three <= 649:
        return True  # Discover
    if 3528 <= first_four <= 3589:  # JCB
        return True
    if first_two in (36, 38) or 300 <= first_three <= 305:  # Diners Club
        return True
    if first_four in _CARD_ISSUER_PREFIXES:  # Maestro
        return True
    return first_two == 62  # UnionPay


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, character in enumerate(reversed(digits)):
        value = int(character)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0
