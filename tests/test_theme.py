"""Tests for the theme tokens and the light-theme structure."""

from __future__ import annotations

from clipnest.ui.theme import DARK, LIGHT, palette, stylesheet, theme


def test_dark_is_the_default_theme() -> None:
    assert theme().name == "dark"
    assert theme().accent == DARK.accent


def test_dark_uses_charcoal_surfaces_and_a_purple_accent() -> None:
    assert DARK.background.lower() == "#141317"
    assert DARK.accent.lower() == "#a273ff"
    assert DARK.surface != DARK.background


def test_light_theme_is_a_full_alternative() -> None:
    css = stylesheet(LIGHT)
    assert LIGHT.accent != DARK.accent
    assert LIGHT.background in css
    assert LIGHT.text in css


def test_stylesheet_covers_the_main_surfaces() -> None:
    css = stylesheet(DARK)
    for selector in (
        "QWidget#Sidebar",
        "QToolButton#NavButton",
        "QLineEdit#SearchInput",
        "QFrame#SnippetCard",
        "QFrame#DetailPanel",
        "QFrame#NotificationBar",
        "QFrame#Card",
        "QFrame#StateIconBox",
    ):
        assert selector in css


def test_stylesheet_covers_the_settings_page() -> None:
    for tokens in (DARK, LIGHT):
        css = stylesheet(tokens)
        for selector in (
            "QWidget#SettingsPage",
            "QWidget#SettingsBody",
            "QScrollArea#SettingsScroll",
            "QLabel#SettingsHeading",
            "QLabel#SettingsHint",
            "QLabel#SettingsError",
            "QLabel#SettingsPath",
            "QPushButton#ChoiceButton",
            "QLabel#ShortcutKey",
            "QSpinBox#HistoryLimitInput",
        ):
            assert selector in css, selector
        assert tokens.accent in css


def test_palette_matches_the_stylesheet(qapp) -> None:
    dark_palette = palette(DARK)
    light_palette = palette(LIGHT)

    assert dark_palette.window().color().name().lower() == DARK.background
    assert light_palette.window().color().name().lower() == LIGHT.background
