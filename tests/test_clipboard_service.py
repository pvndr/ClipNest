"""Tests for the clipboard monitoring service.

Everything here runs against ``FakeClipboard``: the system clipboard is never
read or written by the suite.
"""

from __future__ import annotations

import pytest

from clipnest.core.clipboard import DEFAULT_MAX_TEXT_LENGTH, ClipboardService
from clipnest.core.storage import ClipboardRepository, StorageError
from tests.fakes import FakeClipboard


def test_captures_plain_text(
    clipboard_service: ClipboardService,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    fake_clipboard.simulate_copy("hello clipboard")

    assert [entry.text for entry in repository.list_entries()] == ["hello clipboard"]


def test_emits_entry_captured_signal(
    clipboard_service: ClipboardService,
    fake_clipboard: FakeClipboard,
) -> None:
    captured = []
    clipboard_service.entry_captured.connect(captured.append)

    fake_clipboard.simulate_copy("signal payload")

    assert len(captured) == 1
    assert captured[0].text == "signal payload"


def test_ignores_empty_and_whitespace_only_text(
    clipboard_service: ClipboardService,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    for value in ("", "   ", "\n\t  \r\n"):
        fake_clipboard.simulate_copy(value)

    assert repository.count() == 0


def test_truncates_long_text(qapp, repository, fake_clipboard) -> None:
    service = ClipboardService(fake_clipboard, repository, max_text_length=10)
    service.start()
    try:
        fake_clipboard.simulate_copy("x" * 25)
    finally:
        service.stop()

    assert repository.list_entries()[0].text == "x" * 10


def test_truncation_is_announced_with_the_original_length(
    qapp, repository, fake_clipboard
) -> None:
    service = ClipboardService(fake_clipboard, repository, max_text_length=10)
    announced: list[tuple[object, int]] = []
    service.capture_truncated.connect(
        lambda entry, original: announced.append((entry, original))
    )
    service.start()
    try:
        fake_clipboard.simulate_copy("x" * 25)
    finally:
        service.stop()

    assert len(announced) == 1
    entry, original_length = announced[0]
    assert original_length == 25
    assert len(entry.text) == 10


def test_short_text_does_not_announce_truncation(
    clipboard_service: ClipboardService, fake_clipboard: FakeClipboard
) -> None:
    announced: list[tuple[object, int]] = []
    clipboard_service.capture_truncated.connect(
        lambda entry, original: announced.append((entry, original))
    )

    fake_clipboard.simulate_copy("short")

    assert announced == []


def test_max_text_length_is_exposed(
    clipboard_service: ClipboardService,
) -> None:
    assert clipboard_service.max_text_length == DEFAULT_MAX_TEXT_LENGTH


def test_ignores_consecutive_duplicates(
    clipboard_service: ClipboardService,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    fake_clipboard.simulate_copy("repeat")
    fake_clipboard.simulate_copy("repeat")
    assert repository.count() == 1

    fake_clipboard.simulate_copy("different")
    fake_clipboard.simulate_copy("repeat")

    assert repository.count() == 3


def test_duplicate_detection_is_seeded_from_history(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    repository.add("already stored")

    service = ClipboardService(fake_clipboard, repository)
    service.start()
    try:
        fake_clipboard.simulate_copy("already stored")
    finally:
        service.stop()

    assert repository.count() == 1


def test_oversized_repeat_is_stored_once(qapp, repository, fake_clipboard) -> None:
    """Repeats are compared on the stored (truncated) text, not the raw copy."""
    service = ClipboardService(fake_clipboard, repository, max_text_length=10)
    service.start()
    try:
        fake_clipboard.simulate_copy("x" * 25)
        fake_clipboard.simulate_copy("x" * 25)
    finally:
        service.stop()

    assert repository.count() == 1


def test_oversized_repeat_is_recognised_after_a_restart(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    repository.add("y" * 10)

    service = ClipboardService(fake_clipboard, repository, max_text_length=10)
    service.start()
    try:
        fake_clipboard.simulate_copy("y" * 40)
    finally:
        service.stop()

    assert repository.count() == 1


def test_capture_resumes_after_the_history_is_cleared(
    clipboard_service: ClipboardService,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    fake_clipboard.simulate_copy("copied again")
    repository.clear_unpinned()

    fake_clipboard.simulate_copy("copied again")

    assert [entry.text for entry in repository.list_entries()] == ["copied again"]


def test_capture_resumes_after_the_newest_entry_is_deleted(
    clipboard_service: ClipboardService,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    fake_clipboard.simulate_copy("delete then copy")
    repository.delete(repository.list_entries()[0].id)

    fake_clipboard.simulate_copy("delete then copy")

    assert [entry.text for entry in repository.list_entries()] == ["delete then copy"]


def test_text_that_is_blank_once_truncated_is_ignored(
    qapp, repository, fake_clipboard
) -> None:
    service = ClipboardService(fake_clipboard, repository, max_text_length=10)
    service.start()
    try:
        fake_clipboard.simulate_copy(" " * 20 + "content")
    finally:
        service.stop()

    assert repository.count() == 0


def test_pause_stops_capture_and_resume_restarts_it(
    clipboard_service: ClipboardService,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    clipboard_service.pause()
    fake_clipboard.simulate_copy("while paused")
    assert repository.count() == 0
    assert clipboard_service.is_paused is True

    clipboard_service.resume()
    fake_clipboard.simulate_copy("after resume")

    assert repository.count() == 1
    assert clipboard_service.is_paused is False


def test_paused_changed_only_emits_on_transition(
    clipboard_service: ClipboardService,
) -> None:
    states: list[bool] = []
    clipboard_service.paused_changed.connect(states.append)

    clipboard_service.pause()
    clipboard_service.pause()
    clipboard_service.resume()
    clipboard_service.resume()

    assert states == [True, False]


def test_toggle_paused_returns_new_state(clipboard_service: ClipboardService) -> None:
    assert clipboard_service.toggle_paused() is True
    assert clipboard_service.toggle_paused() is False


def test_copy_back_is_not_recorded(
    clipboard_service: ClipboardService,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    fake_clipboard.simulate_copy("first")
    fake_clipboard.simulate_copy("second")
    assert repository.count() == 2

    assert clipboard_service.copy_text("first") is True

    assert fake_clipboard.text() == "first"
    assert repository.count() == 2


def test_copy_back_suppresses_delayed_notification(qapp, repository) -> None:
    clipboard = FakeClipboard()
    clipboard.emit_on_set = False  # emulate platforms that notify later
    service = ClipboardService(clipboard, repository)
    service.start()
    try:
        service.copy_text("copied from ClipNest")
        clipboard.dataChanged.emit()
    finally:
        service.stop()

    assert repository.count() == 0


def test_capture_works_again_after_suppression_window(qapp, repository) -> None:
    clipboard = FakeClipboard()
    service = ClipboardService(clipboard, repository, self_copy_window=-1.0)
    service.start()
    try:
        clipboard.simulate_copy("before")
        service.copy_text("outside the window")
    finally:
        service.stop()

    assert repository.count() == 2


def test_clipboard_read_failure_reports_error(
    clipboard_service: ClipboardService,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    errors: list[str] = []
    clipboard_service.error_occurred.connect(errors.append)
    fake_clipboard.read_error = RuntimeError("clipboard is busy")

    fake_clipboard.dataChanged.emit()

    assert repository.count() == 0
    assert len(errors) == 1
    assert "unavailable" in errors[0]


def test_storage_failure_reports_error(qapp, fake_clipboard) -> None:
    class BrokenRepository:
        def latest_text(self) -> str | None:
            return None

        def add(self, text: str) -> None:
            raise StorageError("disk full")

    service = ClipboardService(fake_clipboard, BrokenRepository())
    errors: list[str] = []
    service.error_occurred.connect(errors.append)
    service.start()
    try:
        fake_clipboard.simulate_copy("cannot be stored")
    finally:
        service.stop()

    assert len(errors) == 1
    assert "disk full" in errors[0]


def test_retention_applies_while_capturing(tmp_path) -> None:
    repository = ClipboardRepository(tmp_path / "limited.db", history_limit=2)
    clipboard = FakeClipboard()
    service = ClipboardService(clipboard, repository)
    service.start()
    try:
        for index in range(4):
            clipboard.simulate_copy(f"item {index}")
    finally:
        service.stop()

    assert [entry.text for entry in repository.list_entries()] == ["item 3", "item 2"]


def test_stop_disconnects_from_clipboard(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    service = ClipboardService(fake_clipboard, repository)
    service.start()
    service.stop()

    fake_clipboard.simulate_copy("after stop")

    assert repository.count() == 0
    assert service.is_running is False


def test_start_is_idempotent(
    clipboard_service: ClipboardService,
    fake_clipboard: FakeClipboard,
    repository: ClipboardRepository,
) -> None:
    clipboard_service.start()

    fake_clipboard.simulate_copy("captured once")

    assert repository.count() == 1


def test_invalid_max_text_length_is_rejected(qapp, repository, fake_clipboard) -> None:
    with pytest.raises(ValueError):
        ClipboardService(fake_clipboard, repository, max_text_length=0)
