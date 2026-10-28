"""Lightweight content classification for clipboard snippets.

Pure Python: no Qt, no I/O, no storage. The UI uses this to filter the history
by content type and to pick a card icon; the repository stays unaware of it.

The rules are heuristics, not a parser: they must be cheap enough to run over
hundreds of entries on every keystroke of the search box.
"""

from __future__ import annotations

import re
from enum import Enum


class TextKind(str, Enum):
    """Kind of content stored in a snippet."""

    TEXT = "text"
    LINK = "link"
    CODE = "code"


_URL_RE = re.compile(r"^(?:https?|ftp)://\S+$", re.IGNORECASE)
_MAILTO_RE = re.compile(r"^mailto:\S+$", re.IGNORECASE)
_DOMAIN_RE = re.compile(
    r"^(?:[\w-]+\.)+[a-z]{2,}(?::\d+)?(?:/\S*)?$", re.IGNORECASE
)

# Markers that hint at source code. Individually they are ambiguous ("a; b"),
# so they only contribute to a score.
_CODE_MARKERS = (
    re.compile(r"[;{}]\s*$"),
    re.compile(
        r"^\s*(?:def|class|import|from|package|using|namespace|public|private|"
        r"protected|func|fn|const|let|var|function|return|throw|async|await)\b"
    ),
    re.compile(r"^\s*(?://|/\*|\*/|\*|#include|#!)"),
    re.compile(r"(?:=>|::|->|&&|\|\|)"),
    re.compile(r"</?[a-z][\w-]*(?:\s[^>]*)?>", re.IGNORECASE),
    # A quoted key, as in ``{"name": "value"}`` or ``"id": 3,``.
    re.compile(r"^[\s\[\{]*(?:\"[^\"]*\"|'[^']*')\s*:"),
)

# Unambiguous source-code constructs: a single hit is enough regardless of shape.
_DEFINITE_CODE_RE = re.compile(
    r"^\s*(?:def\s+\w+\s*\(|class\s+\w+\s*[:(]|import\s+[\w.]+|"
    r"from\s+[\w.]+\s+import|#include\s*[<\"]|package\s+[\w.]+;|"
    r"using\s+namespace|namespace\s+\w+|function\s+\w+\s*\(|"
    r"func\s+\w+\s*\(|(?:public|private|protected)\s+[\w<>\[\]]+\s+\w+\s*\(|"
    r"(?:const|let|var)\s+\w+\s*=|```)"
)

# Markers strong enough to classify a single-line snippet as code.
_STRONG_CODE_MARKERS = (
    re.compile(
        r"^\s*(?:def|class|import|from|package|using|namespace|public|private|"
        r"func|fn|const|let|var|function)\b.*[:{(=]"
    ),
    re.compile(r"^\s*(?:return|throw|await|yield)\b.*[;)]\s*$"),
    re.compile(
        r"^\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b.*;?\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*</?[a-z][\w-]*(?:\s[^>]*)?>"),
    re.compile(r"(?:=>|::|->)"),
    re.compile(r"^\s*(?://|/\*|#include|#!)"),
    # A bare call expression such as ``print("hi")`` or ``self.save();``.
    re.compile(r"^\s*(?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*\([^()]*\)\s*[;{]?\s*$"),
    # An inline object or array literal, e.g. ``{"id": 3}``.
    re.compile(r"^\s*[\[\{].*:.*[\]\}]\s*$"),
)


def classify_text(text: str) -> TextKind:
    """Return the kind of ``text``: link, code, or plain text."""
    stripped = text.strip()
    if not stripped:
        return TextKind.TEXT
    if _looks_like_link(stripped):
        return TextKind.LINK
    if _looks_like_code(stripped):
        return TextKind.CODE
    return TextKind.TEXT


def _looks_like_link(text: str) -> bool:
    candidate = text.rstrip(".,;:!?)]}\"'")
    if any(character.isspace() for character in candidate):
        return False
    return bool(
        _URL_RE.match(candidate)
        or _MAILTO_RE.match(candidate)
        or _DOMAIN_RE.match(candidate)
    )


def _looks_like_code(text: str) -> bool:
    lines = text.splitlines()
    if any(_DEFINITE_CODE_RE.match(line) for line in lines):
        return True
    if len(lines) == 1:
        return any(marker.search(text) for marker in _STRONG_CODE_MARKERS)

    marker_hits = sum(
        1 for line in lines if any(marker.search(line) for marker in _CODE_MARKERS)
    )
    indented = sum(
        1 for line in lines if line.startswith(("  ", "\t")) and line.strip()
    )
    if marker_hits >= 2:
        return True
    return marker_hits >= 1 and indented >= 2
