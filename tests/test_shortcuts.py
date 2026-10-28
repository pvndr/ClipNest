"""Tests for the in-app keyboard shortcuts (Ctrl+K and Escape).

The shortcuts are window-scoped, so the tests drive them with real key presses
against a shown window and then assert on focus, search text, and visibility.
No global (system-wide) hotkey is registered, so none is tested here.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from clipnest.core.storage import ClipboardRepository
from clipnest.ui.main_window import MainWindow


@pytest.fixture
def shown(window: MainWindow, qapp):
    """A visible window, so key events reach its shortcuts."""
    window.show()
    window.activateWindow()
    qapp.processEvents()
    yield window
    window.set_hide_on_close(False)
    window.close()
    window.deleteLater()


def _press(key: Qt.Key, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
    """Deliver a key press to whichever widget currently holds the focus."""
    target = QApplication.focusWidget() or QApplication.activeWindow()
    assert target is not None
    QTest.keyClick(target, key, modifiers)
    QTest.qWait(10)


def _press_ctrl_k() -> None:
    _press(Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)


# ---------------------------------------------------------------- registration


def test_shortcuts_are_window_scoped_with_the_documented_keys(
    window: MainWindow,
) -> None:
    assert window.shortcuts["focus_search"].key().toString() == "Ctrl+K"
    assert window.shortcuts["escape"].key().toString() == "Esc"

    for shortcut in window.shortcuts.values():
        assert shortcut.context() == Qt.ShortcutContext.WindowShortcut
        assert shortcut.isEnabled() is True


# -------------------------------------------------------------------- Ctrl+K


def test_ctrl_k_focuses_the_search_field(shown: MainWindow) -> None:
    shown.pause_button.setFocus()
    assert shown.search_input.hasFocus() is False

    _press_ctrl_k()

    assert shown.search_input.hasFocus() is True


def test_ctrl_k_returns_to_history_from_the_settings_page(
    shown: MainWindow, qapp
) -> None:
    shown.sidebar.buttons()["settings"].click()
    qapp.processEvents()
    assert shown.content_stack.currentWidget() is shown.settings_page

    _press_ctrl_k()

    assert shown.sidebar.current_category == "all"
    assert shown.content_stack.currentWidget() is shown.history_page
    assert shown.search_input.hasFocus() is True


def test_ctrl_k_inside_the_search_field_does_not_duplicate_input(
    shown: MainWindow,
) -> None:
    shown.search_input.setText("pinned note")
    shown.search_input.setFocus()
    shown.search_input.setCursorPosition(0)

    _press_ctrl_k()

    assert shown.search_input.text() == "pinned note"
    assert shown.search_input.hasFocus() is True
    assert shown.search_input.cursorPosition() == 0


# ------------------------------------------------------------------- Escape


def test_escape_clears_an_active_search_first(
    shown: MainWindow, fake_clipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("alpha")
    fake_clipboard.simulate_copy("beta")
    shown.search_input.setText("alpha")
    shown.search_input.setFocus()
    shown._notify("still here", "info", timeout_ms=None)
    assert shown.history_view.count() == 1

    _press(Qt.Key.Key_Escape)

    assert shown.search_input.text() == ""
    assert shown.history_view.count() == 2
    # Only one action per press: the notification is untouched.
    assert shown.notification.isVisible() is True
    assert shown.isVisible() is True


def test_escape_moves_focus_away_from_an_empty_search(shown: MainWindow) -> None:
    shown.search_input.setText("")
    shown.search_input.setFocus()
    assert shown.search_input.hasFocus() is True

    _press(Qt.Key.Key_Escape)

    assert shown.search_input.hasFocus() is False
    assert shown.isVisible() is True


def test_escape_dismisses_a_visible_notification(shown: MainWindow) -> None:
    shown._notify("dismiss me", "info", timeout_ms=None)
    shown.pause_button.setFocus()
    assert shown.notification.isVisible() is True

    _press(Qt.Key.Key_Escape)

    assert shown.notification.isHidden() is True
    assert shown.isVisible() is True


def test_escape_never_closes_or_hides_the_window(
    shown: MainWindow, qapp
) -> None:
    hidden: list[bool] = []
    shown.hidden_to_tray.connect(lambda: hidden.append(True))
    shown.set_hide_on_close(True)

    for _ in range(3):
        _press(Qt.Key.Key_Escape)

    qapp.processEvents()
    assert shown.isVisible() is True
    assert shown.isHidden() is False
    assert hidden == []


def test_escape_on_the_settings_page_leaves_the_page_and_search_alone(
    shown: MainWindow, qapp
) -> None:
    shown.search_input.setText("keep me")
    shown.sidebar.buttons()["settings"].click()
    qapp.processEvents()

    _press(Qt.Key.Key_Escape)

    assert shown.content_stack.currentWidget() is shown.settings_page
    assert shown.search_input.text() == "keep me"
    assert shown.isVisible() is True
