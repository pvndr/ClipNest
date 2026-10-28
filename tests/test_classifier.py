"""Tests for the lightweight content classifier used by category filters."""

from __future__ import annotations

import pytest

from clipnest.core.classifier import TextKind, classify_text


@pytest.mark.parametrize(
    "text",
    [
        "https://example.com",
        "http://example.com/path?query=1#frag",
        "example.com",
        "sub.example.co.uk/docs/page",
        "mailto:someone@example.com",
    ],
)
def test_links_are_recognised(text: str) -> None:
    assert classify_text(text) is TextKind.LINK


@pytest.mark.parametrize(
    "text",
    [
        "def greet(name):\n    return f'hello {name}'",
        "import os\nfrom pathlib import Path",
        "print('hello world')",
        "SELECT * FROM users;",
        '<div class="card">',
        "const total = price * qty;",
        "// TODO: tidy this up",
        "value => value * 2",
        '{"name": "clipnest", "id": 3}',
    ],
)
def test_code_is_recognised(text: str) -> None:
    assert classify_text(text) is TextKind.CODE


@pytest.mark.parametrize(
    "text",
    [
        "Remember the milk",
        "Meet me at 5; then leave",
        "See figure (b) for details",
        "Shopping list:\n  milk\n  eggs",
        "",
        "   ",
    ],
)
def test_plain_text_is_the_default(text: str) -> None:
    assert classify_text(text) is TextKind.TEXT


def test_links_win_over_code_lookalikes() -> None:
    assert classify_text("https://example.com/def/return") is TextKind.LINK
