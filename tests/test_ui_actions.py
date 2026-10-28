"""Tests for snippet actions, clear-history confirmation, and truncation."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from clipnest.core.storage import ClipboardRepository
from clipnest.ui.dialogs import clear_history_body, create_clear_history_dialog
from clipnest.ui.main_window import MainWindow
from tests.fakes import FakeClipboard

MAX_TEXT_LENGTH = 10_000


def _select_text(window: MainWindow, repository: ClipboardRepository, text: str) -> int:
    entry = next(entry for entry in repository.list_entries() if entry.text == text)
    window.history_view.select(entry.id)
    return entry.id


def test_detail_copy_again_copies_without_adding_history(
    window: MainWindow, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("reusable value")
    fake_clipboard.simulate_copy("something else")
    _select_text(window, repository, "reusable value")

    window.detail_panel.copy_button.click()

    assert fake_clipboard.text() == "reusable value"
    assert repository.count() == 2
    assert window.notification.message == "Copied to clipboard"


def test_detail_pin_button_updates_repository_and_view(
    window: MainWindow, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("pin me")
    entry_id = _select_text(window, repository, "pin me")

    window.detail_panel.pin_button.click()

    assert repository.get(entry_id).pinned is True
    assert window.history_view.rows[0].pin_button.isChecked() is True
    assert window.detail_panel.pin_button.text() == "Unpin"


def test_detail_unpin_button_clears_the_pinned_state(
    window: MainWindow, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("pin me")
    entry_id = _select_text(window, repository, "pin me")
    window.detail_panel.pin_button.click()

    window.detail_panel.pin_button.click()

    assert repository.get(entry_id).pinned is False
    assert window.detail_panel.pin_button.text() == "Pin"


def test_detail_delete_removes_the_entry_from_the_interface(
    window: MainWindow, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("keep")
    fake_clipboard.simulate_copy("remove")
    entry_id = _select_text(window, repository, "remove")

    window.detail_panel.delete_button.click()

    assert repository.get(entry_id) is None
    assert window.history_view.count() == 1
    assert window.notification.message == "Snippet deleted"
    assert window.detail_panel.content.toPlainText() == "keep"


def test_pin_on_a_snippet_that_no_longer_exists_is_not_reported_as_success(
    window: MainWindow, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("vanished")
    entry_id = _select_text(window, repository, "vanished")
    # The panel still holds the entry the store no longer has.
    repository.delete(entry_id)

    window.detail_panel.pin_button.click()

    assert repository.count() == 0
    assert window.history_view.count() == 0
    assert "pinned" not in window.notification.message.lower()


def test_delete_key_removes_the_selected_entry(
    window: MainWindow, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("keep")
    fake_clipboard.simulate_copy("remove")
    entry_id = _select_text(window, repository, "remove")
    card = window.history_view.selected_card()
    assert card is not None

    QTest.keyClick(card, Qt.Key.Key_Delete)

    assert repository.get(entry_id) is None
    assert window.history_view.count() == 1


def test_clear_history_does_nothing_when_cancelled(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
    monkeypatch,
) -> None:
    fake_clipboard.simulate_copy("keep me")
    fake_clipboard.simulate_copy("delete me")
    window.history_view.rows[-1].pin_button.click()
    asked: list[tuple[int, int]] = []

    def refuse(unpinned: int, pinned: int) -> bool:
        asked.append((unpinned, pinned))
        return False

    monkeypatch.setattr(window, "_confirm_clear_history", refuse)

    window.clear_button.click()

    assert asked == [(1, 1)]
    assert repository.count() == 2
    assert window.history_view.count() == 2
    assert "Cleared" not in window.notification.message


def test_clear_history_removes_unpinned_and_keeps_pinned(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
    monkeypatch,
) -> None:
    fake_clipboard.simulate_copy("keep me")
    fake_clipboard.simulate_copy("delete me")
    window.history_view.rows[-1].pin_button.click()
    monkeypatch.setattr(window, "_confirm_clear_history", lambda *args: True)

    window.clear_button.click()

    assert [entry.text for entry in repository.list_entries()] == ["keep me"]
    assert repository.list_entries()[0].pinned is True
    assert window.history_view.count() == 1
    assert window.clear_button.isEnabled() is False
    assert "Pinned kept" in window.notification.message


def test_clear_history_still_captures_the_same_text_again(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
    monkeypatch,
) -> None:
    fake_clipboard.simulate_copy("copied before the clear")
    monkeypatch.setattr(window, "_confirm_clear_history", lambda *args: True)

    window.clear_button.click()
    fake_clipboard.simulate_copy("copied before the clear")

    assert [entry.text for entry in repository.list_entries()] == [
        "copied before the clear"
    ]
    assert window.history_view.count() == 1


def test_clear_history_reports_when_only_pinned_remains(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    fake_clipboard.simulate_copy("pinned only")
    window.history_view.rows[-1].pin_button.click()

    # Nothing unpinned is left, so the control is disabled...
    assert window.clear_button.isEnabled() is False

    # ...and the handler explains why instead of opening a dialog.
    window._on_clear_history()

    assert repository.count() == 1
    assert window.notification.message.startswith("Nothing to clear")


def test_clear_dialog_explains_what_is_kept() -> None:
    body = clear_history_body(3, 2)

    assert "3 unpinned snippets" in body
    assert "Pinned snippets are kept" in body
    assert "2 pinned snippets currently saved" in body


def test_clear_dialog_singular_wording() -> None:
    body = clear_history_body(1, 0)

    assert "1 unpinned snippet" in body
    assert "Pinned snippets are kept" in body


def test_clear_dialog_cancel_button_rejects(qapp) -> None:
    dialog = create_clear_history_dialog(None, 2, 1)

    assert dialog.confirm_button.text() == "Clear history"
    assert dialog.cancel_button.text() == "Cancel"
    assert dialog.cancel_button.isDefault() is True

    dialog.cancel_button.click()

    assert dialog.result() == int(dialog.DialogCode.Rejected)


def test_clear_dialog_confirm_button_accepts(qapp) -> None:
    dialog = create_clear_history_dialog(None, 2, 1)

    dialog.confirm_button.click()

    assert dialog.result() == int(dialog.DialogCode.Accepted)


def test_truncated_capture_is_flagged_in_the_interface(
    window: MainWindow, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("A" * (MAX_TEXT_LENGTH + 2_500))

    stored = repository.list_entries()[0]
    assert len(stored.text) == MAX_TEXT_LENGTH
    assert window.notification.severity == "warning"
    assert "trimmed to 10,000 of 12,500" in window.notification.message
    assert "12,500" in window.notification.message
    assert "10,000" in window.notification.message
    assert window.history_view.rows[0].trimmed_badge.isHidden() is False
    window.history_view.select(stored.id)
    assert window.detail_panel.trimmed_note.isHidden() is False
    assert "Trimmed to 10,000 characters" in window.detail_panel.trimmed_note.text()


def test_untrimmed_capture_has_no_truncation_warning(
    window: MainWindow, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("short value")

    stored = repository.list_entries()[0]
    assert window.notification.isHidden() is True
    assert window.history_view.rows[0].trimmed_badge.isHidden() is True
    window.history_view.select(stored.id)
    assert window.detail_panel.trimmed_note.isHidden() is True


def test_paused_monitoring_survives_ui_interactions(
    window: MainWindow,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
    qapp,
) -> None:
    window.pause_button.click()

    fake_clipboard.simulate_copy("ignored while paused")
    window.search_input.setText("anything")
    qapp.processEvents()
    window.sidebar.buttons()["pinned"].click()
    window.sidebar.buttons()["all"].click()
    qapp.processEvents()

    assert window._clipboard.is_paused is True
    assert window.pause_banner.isHidden() is False
    assert repository.count() == 0

    window.pause_banner.action_button.click()

    assert window._clipboard.is_paused is False
    assert window.pause_banner.isHidden() is True


def test_settings_page_is_editable_and_about_stays_informational(
    window: MainWindow, qapp
) -> None:
    window.sidebar.buttons()["settings"].click()
    qapp.processEvents()

    assert window.content_stack.currentWidget() is window.settings_page
    assert window.settings_page.limit_input.value() == 500
    assert window.detail_panel.isHidden() is True

    window.sidebar.buttons()["about"].click()
    qapp.processEvents()

    assert window.content_stack.currentWidget() is window.info_page
    assert "ClipNest" in window.info_rows["primary"].text()
    assert "no telemetry" in window.info_rows["quaternary"].text()

    window.sidebar.buttons()["all"].click()

    assert window.content_stack.currentWidget() is window.history_page
