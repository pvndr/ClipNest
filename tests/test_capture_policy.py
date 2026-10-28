"""Capture-policy tests: what ClipNest is allowed to turn into history.

These tests drive the clipboard service with a scripted marker provider, so the
whole pipeline (paused check, markers, text read, persistence) is exercised
without the real clipboard and without the real database.
"""

from __future__ import annotations

from clipnest.core.clipboard import ClipboardService
from clipnest.core.clipboard_flags import ClipboardFlagsError, ClipboardPrivacy
from clipnest.core.storage import ClipboardRepository
from tests.fakes import FakeClipboard, FakeClipboardFlags

SECRET_TEXT = "canary-value-1284"


def make_service(
    repository: ClipboardRepository,
    clipboard: FakeClipboard,
    flags: FakeClipboardFlags,
) -> ClipboardService:
    service = ClipboardService(
        clipboard=clipboard, repository=repository, flags_provider=flags
    )
    service.start()
    return service


def test_no_objection_still_captures(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    flags = FakeClipboardFlags(ClipboardPrivacy(history_allowed=True))
    service = make_service(repository, fake_clipboard, flags)
    try:
        fake_clipboard.simulate_copy("ordinary text")
    finally:
        service.stop()

    assert [entry.text for entry in repository.list_entries()] == ["ordinary text"]
    assert flags.reads == 1


def test_exclusion_marker_skips_capture_without_reading_text(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    flags = FakeClipboardFlags(ClipboardPrivacy(excluded=True))
    service = make_service(repository, fake_clipboard, flags)
    skipped: list[str] = []
    captured: list[object] = []
    service.capture_skipped.connect(skipped.append)
    service.entry_captured.connect(captured.append)
    try:
        fake_clipboard.simulate_copy(SECRET_TEXT)
    finally:
        service.stop()

    assert repository.count() == 0
    assert captured == []
    assert skipped == ["marker"]
    # The marker check ran before the text was touched.
    assert fake_clipboard.read_calls == 0


def test_history_marker_zero_skips_capture(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    flags = FakeClipboardFlags(ClipboardPrivacy(history_allowed=False))
    service = make_service(repository, fake_clipboard, flags)
    skipped: list[str] = []
    service.capture_skipped.connect(skipped.append)
    try:
        fake_clipboard.simulate_copy(SECRET_TEXT)
    finally:
        service.stop()

    assert repository.count() == 0
    assert skipped == ["history"]
    assert fake_clipboard.read_calls == 0


def test_invalid_history_marker_skips_capture(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    flags = FakeClipboardFlags(ClipboardPrivacy(history_invalid=True))
    service = make_service(repository, fake_clipboard, flags)
    skipped: list[str] = []
    service.capture_skipped.connect(skipped.append)
    try:
        fake_clipboard.simulate_copy(SECRET_TEXT)
    finally:
        service.stop()

    assert repository.count() == 0
    assert skipped == ["invalid"]


def test_unreadable_markers_skip_capture_and_are_announced(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    flags = FakeClipboardFlags(error=ClipboardFlagsError("clipboard is locked"))
    service = make_service(repository, fake_clipboard, flags)
    skipped: list[str] = []
    errors: list[str] = []
    service.capture_skipped.connect(skipped.append)
    service.error_occurred.connect(errors.append)
    try:
        fake_clipboard.simulate_copy(SECRET_TEXT)
    finally:
        service.stop()

    assert repository.count() == 0
    assert skipped == ["unreadable"]
    assert errors == []


def test_unsupported_platform_captures_normally(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    flags = FakeClipboardFlags(supported=False)
    service = make_service(repository, fake_clipboard, flags)
    try:
        fake_clipboard.simulate_copy("still captured")
    finally:
        service.stop()

    assert [entry.text for entry in repository.list_entries()] == ["still captured"]
    assert flags.reads == 0


def test_paused_monitoring_does_not_even_read_markers(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    flags = FakeClipboardFlags()
    service = make_service(repository, fake_clipboard, flags)
    service.pause()
    try:
        fake_clipboard.simulate_copy(SECRET_TEXT)
    finally:
        service.stop()

    assert flags.reads == 0
    assert fake_clipboard.read_calls == 0
    assert repository.count() == 0


class RecordingRepository(ClipboardRepository):
    """A repository that records which calls the service makes."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.calls: list[str] = []

    def latest_text(self) -> str | None:
        self.calls.append("latest_text")
        return super().latest_text()

    def add(self, text: str, created_at=None):  # noqa: ANN001 - mirrors the parent
        self.calls.append("add")
        return super().add(text, created_at)


def test_excluded_content_costs_no_database_read(
    qapp, tmp_path, fake_clipboard: FakeClipboard
) -> None:
    repository = RecordingRepository(tmp_path / "policy.db")
    flags = FakeClipboardFlags(ClipboardPrivacy(excluded=True))
    service = make_service(repository, fake_clipboard, flags)
    try:
        fake_clipboard.simulate_copy(SECRET_TEXT)
    finally:
        service.stop()

    assert repository.calls == []


def test_allowed_content_is_deduplicated_before_persisting(
    qapp, tmp_path, fake_clipboard: FakeClipboard
) -> None:
    repository = RecordingRepository(tmp_path / "dedupe.db")
    service = make_service(repository, fake_clipboard, FakeClipboardFlags())
    try:
        fake_clipboard.simulate_copy("same value")
        fake_clipboard.simulate_copy("same value")
    finally:
        service.stop()

    assert repository.calls == ["latest_text", "add", "latest_text"]
    assert repository.count() == 1


def test_window_reports_the_skip_without_content(
    window, fake_clipboard: FakeClipboard, fake_flags: FakeClipboardFlags
) -> None:
    fake_flags.privacy = ClipboardPrivacy(excluded=True)

    fake_clipboard.simulate_copy(SECRET_TEXT)

    message = window.notification.message
    assert message
    assert SECRET_TEXT not in message
    assert "excluded" in message


def test_window_keeps_history_empty_for_excluded_content(
    window, repository: ClipboardRepository, fake_clipboard: FakeClipboard, fake_flags
) -> None:
    fake_flags.privacy = ClipboardPrivacy(excluded=True)

    fake_clipboard.simulate_copy(SECRET_TEXT)

    assert repository.count() == 0
    assert window.history_view.count() == 0


# ----------------------------------------------------- sensitive-content policy

SENSITIVE_TEXT = "ghp_" + "canary" * 6


def test_sensitive_content_is_not_stored(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    service = ClipboardService(
        fake_clipboard, repository, flags_provider=FakeClipboardFlags()
    )
    skipped: list[str] = []
    captured: list[object] = []
    service.capture_skipped.connect(skipped.append)
    service.entry_captured.connect(captured.append)
    service.start()
    try:
        fake_clipboard.simulate_copy(SENSITIVE_TEXT)
    finally:
        service.stop()

    assert repository.count() == 0
    assert captured == []
    assert skipped == ["sensitive"]


def test_disabled_detection_stores_the_same_content(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    service = ClipboardService(
        fake_clipboard,
        repository,
        flags_provider=FakeClipboardFlags(),
        sensitive_enabled=False,
    )
    service.start()
    try:
        fake_clipboard.simulate_copy(SENSITIVE_TEXT)
    finally:
        service.stop()

    assert repository.count() == 1


def test_detection_can_be_toggled_at_runtime(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    service = ClipboardService(
        fake_clipboard, repository, flags_provider=FakeClipboardFlags()
    )
    service.set_sensitive_detection(False)
    service.start()
    try:
        fake_clipboard.simulate_copy(SENSITIVE_TEXT)
        service.set_sensitive_detection(True)
        fake_clipboard.simulate_copy(SENSITIVE_TEXT + "-second")
    finally:
        service.stop()

    assert repository.count() == 1
    assert service.sensitive_detection_enabled is True


def test_privacy_markers_are_checked_before_sensitive_rules(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    calls: list[str] = []

    def detector(text: str):
        calls.append(text)
        return None

    flags = FakeClipboardFlags(ClipboardPrivacy(excluded=True))
    service = ClipboardService(
        fake_clipboard,
        repository,
        flags_provider=flags,
        sensitive_detector=detector,
    )
    service.start()
    try:
        fake_clipboard.simulate_copy(SENSITIVE_TEXT)
    finally:
        service.stop()

    assert calls == []
    assert fake_clipboard.read_calls == 0


def test_sensitive_skip_costs_no_database_read(
    qapp, tmp_path, fake_clipboard: FakeClipboard
) -> None:
    repository = RecordingRepository(tmp_path / "sensitive.db")
    service = ClipboardService(
        fake_clipboard, repository, flags_provider=FakeClipboardFlags()
    )
    service.start()
    try:
        fake_clipboard.simulate_copy(SENSITIVE_TEXT)
    finally:
        service.stop()

    assert repository.calls == []


def test_detector_sees_the_stored_truncated_text(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    seen: list[str] = []

    def detector(text: str):
        seen.append(text)
        return None

    service = ClipboardService(
        fake_clipboard,
        repository,
        max_text_length=10,
        flags_provider=FakeClipboardFlags(),
        sensitive_detector=detector,
    )
    service.start()
    try:
        fake_clipboard.simulate_copy("0123456789" + SENSITIVE_TEXT)
    finally:
        service.stop()

    assert seen == ["0123456789"]


def test_detector_is_not_called_for_blank_text(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    seen: list[str] = []
    service = ClipboardService(
        fake_clipboard,
        repository,
        flags_provider=FakeClipboardFlags(),
        sensitive_detector=lambda text: seen.append(text),
    )
    service.start()
    try:
        fake_clipboard.simulate_copy("   \n\t ")
    finally:
        service.stop()

    assert seen == []


def test_self_copy_suppression_runs_before_detection(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    seen: list[str] = []
    service = ClipboardService(
        fake_clipboard,
        repository,
        flags_provider=FakeClipboardFlags(),
        sensitive_detector=lambda text: seen.append(text),
    )
    service.start()
    try:
        service.copy_text(SENSITIVE_TEXT)
    finally:
        service.stop()

    assert seen == []
    assert repository.count() == 0


def test_skip_logging_never_contains_the_value(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard, caplog
) -> None:
    service = ClipboardService(
        fake_clipboard, repository, flags_provider=FakeClipboardFlags()
    )
    service.start()
    try:
        with caplog.at_level("DEBUG"):
            fake_clipboard.simulate_copy(SENSITIVE_TEXT)
    finally:
        service.stop()

    assert caplog.records, "the skip should be logged"
    assert all(SENSITIVE_TEXT not in record.getMessage() for record in caplog.records)


def test_window_reports_a_sensitive_skip_without_content(
    window, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    fake_clipboard.simulate_copy(SENSITIVE_TEXT)

    message = window.notification.message
    assert message == "Not saved: content matched a sensitive-data rule."
    assert "canary" not in message
    assert repository.count() == 0
