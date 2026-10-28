"""ClipNest visual system: colour tokens, stylesheet, and Qt palette.

A single token set drives both the stylesheet and the QPalette, so native
primitives (dialogs, menus, tooltips) inherit the same look as the widgets.
Dark is the default; :data:`LIGHT` exists so a theme switch can be wired up
later without restructuring anything. No switcher UI is exposed today.

Widgets read colours through :func:`theme` (for icons) and never hardcode
hex values, which keeps every surface consistent.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    """Colour tokens for one ClipNest theme."""

    name: str
    background: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_faint: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    accent_border: str
    on_accent: str
    danger: str
    danger_soft: str
    success: str
    success_soft: str
    warning: str
    warning_soft: str


DARK = Theme(
    name="dark",
    background="#141317",
    surface="#1c1b22",
    surface_alt="#24222c",
    surface_hover="#2a2833",
    border="#302e3a",
    border_strong="#43404f",
    text="#eeecf5",
    text_muted="#9c97ad",
    text_faint="#6f6a80",
    accent="#a273ff",
    accent_hover="#b58fff",
    accent_pressed="#8b5cf6",
    accent_soft="rgba(162, 115, 255, 0.16)",
    accent_border="rgba(162, 115, 255, 0.45)",
    on_accent="#16121f",
    danger="#ff7186",
    danger_soft="rgba(255, 113, 134, 0.12)",
    success="#4ade80",
    success_soft="rgba(74, 222, 128, 0.12)",
    warning="#f5c05a",
    warning_soft="rgba(245, 192, 90, 0.12)",
)

LIGHT = Theme(
    name="light",
    background="#f5f4f8",
    surface="#ffffff",
    surface_alt="#f0eef5",
    surface_hover="#e9e6f1",
    border="#e0dcea",
    border_strong="#c9c3d8",
    text="#211e2b",
    text_muted="#6b6580",
    text_faint="#8d87a0",
    accent="#7c4dff",
    accent_hover="#8f66ff",
    accent_pressed="#6a3ce0",
    accent_soft="rgba(124, 77, 255, 0.10)",
    accent_border="rgba(124, 77, 255, 0.35)",
    on_accent="#ffffff",
    danger="#d92d4b",
    danger_soft="rgba(217, 45, 75, 0.09)",
    success="#15803d",
    success_soft="rgba(21, 128, 61, 0.09)",
    warning="#b45309",
    warning_soft="rgba(180, 83, 9, 0.09)",
)

THEMES: dict[str, Theme] = {DARK.name: DARK, LIGHT.name: LIGHT}

_active: Theme = DARK


def theme() -> Theme:
    """Return the theme currently applied to the application."""
    return _active


def stylesheet(t: Theme) -> str:
    """Build the full application stylesheet for ``t``."""
    return f"""
QWidget {{
    color: {t.text};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}

QMainWindow,
QWidget#Root,
QDialog {{
    background-color: {t.background};
}}

/* ------------------------------------------------------------------ sidebar */
QWidget#Sidebar {{
    background-color: {t.surface};
    border-right: 1px solid {t.border};
}}

QLabel#Brand {{
    font-size: 15px;
    font-weight: 600;
    color: {t.text};
}}

QFrame#BrandMark {{
    background-color: {t.accent};
    border-radius: 4px;
}}

QLabel#SectionLabel {{
    color: {t.text_faint};
    font-size: 10px;
    font-weight: 600;
    padding: 2px 4px;
}}

QToolButton#NavButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    color: {t.text_muted};
    font-size: 13px;
    padding: 8px 10px;
    text-align: left;
    icon-size: 18px;
}}

QToolButton#NavButton:hover {{
    background-color: {t.surface_alt};
    color: {t.text};
}}

QToolButton#NavButton:checked {{
    background-color: {t.accent_soft};
    border-color: {t.accent_border};
    color: {t.accent};
    font-weight: 600;
}}

QToolButton#NavButton:focus {{
    border-color: {t.accent_border};
}}

/* ------------------------------------------------------------------- header */
QLabel#PageTitle {{
    font-size: 19px;
    font-weight: 600;
    color: {t.text};
}}

QLabel#PageSubtitle {{
    font-size: 12px;
    color: {t.text_muted};
}}

QLineEdit#SearchInput {{
    background-color: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 10px;
    color: {t.text};
    padding: 9px 12px;
    selection-background-color: {t.accent};
    selection-color: {t.on_accent};
}}

QLineEdit#SearchInput:hover {{
    border-color: {t.border_strong};
}}

QLineEdit#SearchInput:focus {{
    border-color: {t.accent};
    background-color: {t.surface};
}}

/* -------------------------------------------------------------------- cards */
QFrame#SnippetCard {{
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: 10px;
}}

QFrame#SnippetCard:hover {{
    background-color: {t.surface_hover};
    border-color: {t.border_strong};
}}

QFrame#SnippetCard[selected="true"] {{
    background-color: {t.surface_hover};
    border-color: {t.accent};
}}

QFrame#SnippetCard QLabel {{
    background-color: transparent;
}}

QLabel#CardPreview {{
    color: {t.text};
    font-size: 13px;
}}

QLabel#CardPreview[selected="true"] {{
    color: {t.text};
}}

QLabel#CardMeta {{
    color: {t.text_muted};
    font-size: 11px;
}}

QLabel#CardBadge {{
    background-color: {t.accent_soft};
    border-radius: 4px;
    color: {t.accent};
    font-size: 10px;
    font-weight: 600;
    padding: 1px 6px;
}}

QToolButton#CardAction {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: {t.text_muted};
    icon-size: 16px;
    padding: 4px;
}}

QToolButton#CardAction:hover {{
    background-color: {t.surface_alt};
    border-color: {t.border};
    color: {t.text};
}}

QToolButton#CardAction:checked {{
    background-color: {t.accent_soft};
    border-color: {t.accent_border};
    color: {t.accent};
}}

/* ------------------------------------------------------------- detail panel */
QFrame#DetailPanel {{
    background-color: {t.surface};
    border-left: 1px solid {t.border};
}}

QLabel#DetailTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {t.text};
}}

QLabel#DetailLabel {{
    color: {t.text_faint};
    font-size: 11px;
}}

QLabel#DetailValue {{
    color: {t.text};
    font-size: 12px;
}}

QLabel#DetailNote {{
    color: {t.text_muted};
    font-size: 11px;
}}

/* ------------------------------------------------------ generic surface card */
QFrame#Card {{
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: 10px;
}}

QPlainTextEdit#DetailContent {{
    background-color: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 8px;
    color: {t.text};
    padding: 8px;
    selection-background-color: {t.accent};
    selection-color: {t.on_accent};
}}

QFrame#Divider {{
    background-color: {t.border};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* ------------------------------------------------------------------ buttons */
QPushButton {{
    background-color: {t.accent};
    border: 1px solid transparent;
    border-radius: 8px;
    color: {t.on_accent};
    font-weight: 600;
    padding: 8px 16px;
}}

QPushButton:hover {{
    background-color: {t.accent_hover};
}}

QPushButton:pressed {{
    background-color: {t.accent_pressed};
}}

QPushButton:disabled {{
    background-color: {t.surface_alt};
    color: {t.text_faint};
}}

QPushButton#SecondaryButton {{
    background-color: transparent;
    border: 1px solid {t.border};
    color: {t.text};
    font-weight: 500;
}}

QPushButton#SecondaryButton:hover {{
    background-color: {t.surface_alt};
    border-color: {t.border_strong};
}}

QPushButton#SecondaryButton:disabled {{
    border-color: {t.border};
    color: {t.text_faint};
}}

QPushButton#GhostButton {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {t.text_muted};
    font-weight: 500;
    padding: 6px 10px;
}}

QPushButton#GhostButton:hover {{
    background-color: {t.surface_alt};
    color: {t.text};
}}

QPushButton#DangerButton {{
    background-color: {t.danger_soft};
    border: 1px solid transparent;
    color: {t.danger};
    font-weight: 600;
}}

QPushButton#DangerButton:hover {{
    border-color: {t.danger};
}}

/* ------------------------------------------------------------------ settings */
QWidget#SettingsPage,
QWidget#SettingsBody,
QScrollArea#SettingsScroll,
QScrollArea#SettingsScroll > QWidget > QWidget {{
    background-color: transparent;
    border: none;
}}

QLabel#SettingsHeading {{
    font-size: 14px;
    font-weight: 600;
    color: {t.text};
}}

QLabel#SettingsHint {{
    font-size: 12px;
    color: {t.text_muted};
}}

QLabel#SettingsError {{
    font-size: 11px;
    color: {t.danger};
}}

QLabel#SettingsPath {{
    background-color: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 6px;
    color: {t.text_muted};
    font-size: 11px;
    padding: 6px 8px;
}}

QPushButton#ChoiceButton {{
    background-color: transparent;
    border: 1px solid {t.border};
    color: {t.text_muted};
    font-weight: 500;
    padding: 7px 18px;
}}

QPushButton#ChoiceButton:hover {{
    background-color: {t.surface_alt};
    border-color: {t.border_strong};
    color: {t.text};
}}

QPushButton#ChoiceButton:checked {{
    background-color: {t.accent_soft};
    border-color: {t.accent_border};
    color: {t.accent};
    font-weight: 600;
}}

QLabel#ShortcutKey {{
    background-color: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 5px;
    color: {t.text};
    font-size: 11px;
    font-weight: 600;
    padding: 3px 6px;
}}

QSpinBox#HistoryLimitInput {{
    background-color: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 8px;
    color: {t.text};
    padding: 6px 8px;
    selection-background-color: {t.accent};
    selection-color: {t.on_accent};
}}

QSpinBox#HistoryLimitInput:hover {{
    border-color: {t.border_strong};
}}

QSpinBox#HistoryLimitInput:focus {{
    border-color: {t.accent};
    background-color: {t.surface};
}}

QCheckBox#SettingsCheck {{
    color: {t.text};
    font-size: 12px;
    spacing: 8px;
}}

QCheckBox#SettingsCheck::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {t.border_strong};
    border-radius: 4px;
    background-color: {t.surface_alt};
}}

QCheckBox#SettingsCheck::indicator:hover {{
    border-color: {t.accent};
}}

QCheckBox#SettingsCheck::indicator:checked {{
    background-color: {t.accent};
    border-color: {t.accent};
}}

/* ------------------------------------------------------------ notifications */
QFrame#NotificationBar {{
    border: 1px solid {t.border};
    border-radius: 8px;
    background-color: {t.surface_alt};
}}

QFrame#NotificationBar[severity="success"] {{
    background-color: {t.success_soft};
    border-color: transparent;
}}

QFrame#NotificationBar[severity="error"] {{
    background-color: {t.danger_soft};
    border-color: transparent;
}}

QFrame#NotificationBar[severity="warning"] {{
    background-color: {t.warning_soft};
    border-color: transparent;
}}

QFrame#NotificationBar[severity="info"] {{
    background-color: {t.accent_soft};
    border-color: transparent;
}}

QFrame#NotificationBar QLabel {{
    background-color: transparent;
    border: none;
    font-size: 12px;
}}

/* ------------------------------------------------------------------- states */
QFrame#StateIconBox {{
    background-color: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 24px;
}}

QLabel#StateTitle {{
    font-size: 15px;
    font-weight: 600;
    color: {t.text};
}}

QLabel#StateDescription {{
    font-size: 12px;
    color: {t.text_muted};
}}

QLabel#SkeletonBar {{
    background-color: {t.surface_alt};
    border-radius: 6px;
}}

/* ------------------------------------------------------------------- frames */
QFrame#ContentSurface {{
    background-color: {t.background};
    border: none;
}}

QWidget#HistoryScroll,
QWidget#HistoryScroll > QWidget,
QWidget#HistoryContainer {{
    background-color: transparent;
    border: none;
}}

QScrollArea {{
    background-color: transparent;
    border: none;
}}

QStatusBar {{
    background-color: {t.surface};
    border-top: 1px solid {t.border};
    color: {t.text_faint};
    font-size: 11px;
}}

QStatusBar::item {{
    border: none;
}}

QToolTip {{
    background-color: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 6px;
    color: {t.text};
    padding: 4px 8px;
}}

QMenu {{
    background-color: {t.surface};
    border: 1px solid {t.border};
    border-radius: 8px;
    padding: 4px;
}}

QMenu::item {{
    border-radius: 6px;
    padding: 6px 18px 6px 12px;
}}

QMenu::item:selected {{
    background-color: {t.accent_soft};
    color: {t.accent};
}}

QScrollBar:vertical {{
    background: transparent;
    margin: 0;
    width: 10px;
}}

QScrollBar::handle:vertical {{
    background: {t.border_strong};
    border-radius: 5px;
    min-height: 32px;
}}

QScrollBar::handle:vertical:hover {{
    background: {t.accent};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""


def palette(t: Theme) -> QPalette:
    """Build the QPalette matching ``t`` for native primitives."""
    result = QPalette()
    result.setColor(QPalette.ColorRole.Window, QColor(t.background))
    result.setColor(QPalette.ColorRole.WindowText, QColor(t.text))
    result.setColor(QPalette.ColorRole.Base, QColor(t.surface_alt))
    result.setColor(QPalette.ColorRole.AlternateBase, QColor(t.surface))
    result.setColor(QPalette.ColorRole.Text, QColor(t.text))
    result.setColor(QPalette.ColorRole.Button, QColor(t.surface_alt))
    result.setColor(QPalette.ColorRole.ButtonText, QColor(t.text))
    result.setColor(QPalette.ColorRole.Highlight, QColor(t.accent))
    result.setColor(QPalette.ColorRole.HighlightedText, QColor(t.on_accent))
    result.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.surface_alt))
    result.setColor(QPalette.ColorRole.ToolTipText, QColor(t.text))
    result.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.text_faint))
    result.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t.text_faint)
    )
    result.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(t.text_faint),
    )
    return result


def apply_theme(app: QApplication, mode: str = DARK.name) -> Theme:
    """Apply ``mode`` ("dark" or "light") to ``app`` and activate its tokens."""
    global _active
    try:
        selected = THEMES[mode]
    except KeyError as exc:
        raise ValueError(f"Unknown theme: {mode!r}") from exc

    _active = selected
    app.setStyle("Fusion")
    app.setPalette(palette(selected))
    app.setStyleSheet(stylesheet(selected))
    return selected
