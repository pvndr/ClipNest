"""Tests for the main window: rendering, wiring, and user actions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from clipnest.app import create_application
from clipnest.core.storage import ClipboardRepository, StorageError
from clipnest.ui.main_window import DEFAULT_SIZE, MINIMUM_SIZE, MainWindow
from tests.fakes import FakeClipboard


def test_application_is_configured(qapp) -> None:
    app = create_application([])
    assert app.applicationName() == "ClipNest"
    assert app.styleSheet()  # theme stylesheet was applied


def test_window_title_is_clipnest(window: MainWindow) -> None:
    assert window.windowTitle() == "ClipNest"


def test_window_has_expected_size(window: MainWindow) -> None:
    assert (window.width(), window.height()) == DEFAULT_SIZE
    assert (window.minimumWidth(), window.minimumHeight()) == MINIMUM_SIZE


def test_window_starts_with_empty_state(window: MainWindow) -> None:
    assert window.history_view.count() == 0
    assert window.history_view.is_showing_state() is True
    assert (
        window.history_view.state_panel.title_label.text()
        == "No clipboard history yet"
    )
    assert window.search_input.isEnabled() is True
    assert window.clear_button.isEnabled() is False
    assert "0 entries" in window.statusBar().currentMessage()


def test_captured_entry_appears_in_history(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
) -> None:
    fake_clipboard.simulate_copy("a captured value")

    assert window.history_view.count() == 1
    assert window.history_view.is_showing_state() is False
    assert window.clear_button.isEnabled() is True
    assert "1 entry" in window.statusBar().currentMessage()


def test_clicking_row_copies_text_without_new_entry(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    fake_clipboard.simulate_copy("first value")
    fake_clipboard.simulate_copy("second value")
    oldest_row = window.history_view.rows[-1]

    QTest.mouseClick(oldest_row, Qt.MouseButton.LeftButton)

    assert fake_clipboard.text() == "first value"
    assert repository.count() == 2
    assert window.notification.message == "Copied to clipboard"
    assert "Copied to clipboard" in window.statusBar().currentMessage()


def test_pin_button_pins_entry_and_reorders(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    fake_clipboard.simulate_copy("oldest")
    fake_clipboard.simulate_copy("newest")

    window.history_view.rows[-1].pin_button.click()

    assert repository.list_entries()[0].pinned is True
    assert window.history_view.rows[0].pin_button.isChecked() is True
    assert window.notification.message == "Snippet pinned"


def test_pause_button_toggles_service_and_shows_banner(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    assert window.pause_button.text() == "Pause"
    assert window.pause_banner.isHidden() is True

    window.pause_button.click()

    assert window.pause_button.text() == "Resume"
    assert window.pause_banner.isHidden() is False
    assert "paused" in window.pause_banner.message.lower()
    assert "Paused" in window.statusBar().currentMessage()
    fake_clipboard.simulate_copy("ignored while paused")
    assert repository.count() == 0

    window.pause_button.click()

    assert window.pause_button.text() == "Pause"
    assert window.pause_banner.isHidden() is True
    fake_clipboard.simulate_copy("captured again")
    assert repository.count() == 1


def test_search_filters_displayed_entries(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
) -> None:
    fake_clipboard.simulate_copy("alpha value")
    fake_clipboard.simulate_copy("beta value")

    window.search_input.setText("alpha")
    assert window.history_view.count() == 1

    window.search_input.setText("")
    assert window.history_view.count() == 2


def test_service_errors_are_shown_in_status_bar(window: MainWindow) -> None:
    window._clipboard.error_occurred.emit("clipboard is unavailable")

    assert window.statusBar().currentMessage() == "clipboard is unavailable"
    assert window.notification.message == "clipboard is unavailable"
    assert window.notification.severity == "error"


# ------------------------------------------------------ failed history load


def _break_history_reads(monkeypatch, repository: ClipboardRepository) -> None:
    """Make every history read fail the way an unavailable database does."""

    def unavailable(*args, **kwargs):
        raise StorageError("database is locked")

    monkeypatch.setattr(repository, "list_entries", unavailable)
    monkeypatch.setattr(repository, "search", unavailable)


def test_failed_load_drops_every_stale_value_from_the_window(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
    monkeypatch,
) -> None:
    fake_clipboard.simulate_copy("first value")
    fake_clipboard.simulate_copy("second value")
    window.history_view.select(window.history_view.rows[0].entry_id)
    qapp.processEvents()
    selected = window.history_view.selected_id
    assert selected is not None
    assert window.count_label.text() == "2 snippets"
    assert window.clear_button.isEnabled() is True
    assert window.detail_panel.entry_id == selected

    _break_history_reads(monkeypatch, repository)
    # Capturing still succeeds; only reading the list back fails.
    fake_clipboard.simulate_copy("captured while storage is unavailable")

    # The list shows an error instead of the last, unverifiable snapshot.
    assert window.history_view.is_showing_state() is True
    assert (
        window.history_view.state_panel.title_label.text()
        == "Could not load history"
    )
    assert "database is locked" in (
        window.history_view.state_panel.description_label.text()
    )
    assert window.history_view.count() == 0

    # Nothing on screen still claims to describe the last successful load.
    assert window.history_view.selected_id is None
    assert window.detail_panel.entry_id is None
    assert window.count_label.text() == "History unavailable"
    assert window.clear_button.isEnabled() is False

    # The failure stays visible and is reported as an error, not a success.
    assert window.notification.severity == "error"
    assert "database is locked" in window.notification.message
    assert window.statusBar().currentMessage() == "database is locked"

    # A failed read never touches the stored snippets.
    assert repository.count() == 3


def test_failed_search_load_shows_the_same_safe_state(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
    monkeypatch,
) -> None:
    fake_clipboard.simulate_copy("searchable value")
    _break_history_reads(monkeypatch, repository)

    window.search_input.setText("searchable")

    assert window.history_view.is_showing_state() is True
    assert window.history_view.selected_id is None
    assert window.detail_panel.entry_id is None
    assert window.count_label.text() == "History unavailable"
    assert window.clear_button.isEnabled() is False
    assert window.notification.severity == "error"
    assert repository.count() == 1


def test_history_recovery_after_a_failed_load(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
    monkeypatch,
) -> None:
    fake_clipboard.simulate_copy("first value")
    fake_clipboard.simulate_copy("second value")
    _break_history_reads(monkeypatch, repository)
    fake_clipboard.simulate_copy("third value")
    assert window.history_view.is_showing_state() is True
    assert window.count_label.text() == "History unavailable"

    # Storage comes back: the next refresh repaints the real history.
    monkeypatch.undo()
    window.search_input.setText("third")

    assert window.history_view.is_showing_state() is False
    assert window.history_view.count() == 1
    assert window.count_label.text() == "1 snippet"
    assert window.clear_button.isEnabled() is True
    assert window.detail_panel.entry_id == window.history_view.selected_id
    assert "1 entry" in window.statusBar().currentMessage()

    window.search_input.setText("")

    assert window.history_view.count() == 3
    assert window.count_label.text() == "3 snippets"
    assert repository.count() == 3
