"""Tests for the Settings page: appearance, retention, privacy, and pause sync.

The page is driven through its real widgets; the repository, clipboard service,
tray, and preferences are the same objects the application wires together, so
these tests cover the actual signal flow rather than a mock of it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from clipnest import app as app_module
from clipnest.app import create_repository
from clipnest.core.clipboard import ClipboardService
from clipnest.core.storage import ClipboardRepository, StorageError
from clipnest.preferences import (
    MAX_HISTORY_LIMIT,
    MIN_HISTORY_LIMIT,
    Preferences,
)
from clipnest.ui import icons
from clipnest.ui.main_window import MINIMUM_SIZE, MainWindow
from clipnest.ui.settings_page import WrappedLabel
from clipnest.ui.theme import DARK, LIGHT, theme
from clipnest.ui.tray import RESUME_TEXT, TrayIcon
from tests.fakes import FakeClipboard


def _open_settings(window: MainWindow, qapp) -> None:
    window.sidebar.buttons()["settings"].click()
    qapp.processEvents()


def _capture(fake_clipboard: FakeClipboard, *values: str) -> None:
    for value in values:
        fake_clipboard.simulate_copy(value)


# --------------------------------------------------------------- appearance


def test_settings_page_shows_the_current_state(
    window: MainWindow, qapp, repository: ClipboardRepository
) -> None:
    _open_settings(window, qapp)
    page = window.settings_page

    assert window.content_stack.currentWidget() is page
    assert theme().name == DARK.name
    assert page.theme_buttons["dark"].isChecked() is True
    assert page.theme_buttons["light"].isChecked() is False
    assert page.limit_input.value() == repository.history_limit == 500
    assert "unpinned" in page.limit_note.text()
    assert "0 unpinned snippets" in page.limit_note.text()
    assert page.pause_button.text() == "Pause monitoring"


def test_light_choice_applies_the_theme_immediately(
    window: MainWindow, qapp, preferences: Preferences
) -> None:
    _open_settings(window, qapp)
    nav_icon_before = window.sidebar.buttons()["all"].icon().cacheKey()
    window.show()
    qapp.processEvents()

    window.settings_page.theme_buttons["light"].click()
    qapp.processEvents()

    assert theme().name == LIGHT.name
    assert LIGHT.background in qapp.styleSheet()
    assert window.sidebar.buttons()["all"].icon().cacheKey() != nav_icon_before
    assert window.settings_page.theme_buttons["light"].isChecked() is True
    assert window.settings_page.theme_buttons["dark"].isChecked() is False
    # Persisted immediately, so the choice survives a restart.
    assert preferences.theme() == LIGHT.name


def test_choosing_the_active_theme_again_changes_nothing(
    window: MainWindow, qapp, preferences: Preferences
) -> None:
    _open_settings(window, qapp)

    window.settings_page.theme_buttons["dark"].click()
    qapp.processEvents()

    assert theme().name == DARK.name
    assert preferences.theme() == DARK.name
    assert window.settings_page.theme_buttons["dark"].isChecked() is True


def test_theme_choice_survives_a_restart(
    window: MainWindow, qapp, preferences: Preferences, tmp_path: Path
) -> None:
    _open_settings(window, qapp)
    window.settings_page.theme_buttons["light"].click()
    qapp.processEvents()

    # A fresh store over the same file is what the next launch reads.
    from PySide6.QtCore import QSettings

    reopened = Preferences(
        QSettings(str(tmp_path / "clipnest-settings.ini"), QSettings.Format.IniFormat)
    )

    assert reopened.theme() == LIGHT.name


def test_saved_theme_is_applied_at_startup(
    qapp, preferences: Preferences
) -> None:
    preferences.set_theme("light")

    app = app_module.create_application([], theme_mode=preferences.theme())

    assert theme().name == LIGHT.name
    assert LIGHT.background in app.styleSheet()


def test_default_theme_is_used_when_nothing_is_saved(
    qapp, preferences: Preferences
) -> None:
    app = app_module.create_application([], theme_mode=preferences.theme())

    assert theme().name == DARK.name
    assert LIGHT.background not in app.styleSheet()


# ------------------------------------------------------------------ history


def test_applying_a_limit_trims_unpinned_history(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
    preferences: Preferences,
) -> None:
    _capture(fake_clipboard, *[f"value {index}" for index in range(14)])
    assert repository.count(pinned=False) == 14

    _open_settings(window, qapp)
    page = window.settings_page
    page.limit_input.setValue(MIN_HISTORY_LIMIT)
    page.apply_limit_button.click()
    qapp.processEvents()

    assert repository.history_limit == MIN_HISTORY_LIMIT
    assert repository.count(pinned=False) == MIN_HISTORY_LIMIT
    assert preferences.history_limit() == MIN_HISTORY_LIMIT
    assert page.limit_input.value() == MIN_HISTORY_LIMIT
    assert f"{MIN_HISTORY_LIMIT} unpinned snippets" in page.limit_note.text()
    assert "Removed 4 old unpinned snippets" in window.notification.message


def test_applying_a_limit_keeps_pinned_entries(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
) -> None:
    _capture(
        fake_clipboard,
        "keep one",
        "keep two",
        *[f"drop {index}" for index in range(11)],
    )
    entries = {entry.text: entry for entry in repository.list_entries()}
    for text in ("keep one", "keep two"):
        repository.set_pinned(entries[text].id, True)
    assert repository.count(pinned=False) == 11

    _open_settings(window, qapp)
    window.settings_page.limit_input.setValue(MIN_HISTORY_LIMIT)
    window.settings_page.apply_limit_button.click()
    qapp.processEvents()

    assert repository.count(pinned=True) == 2
    assert repository.count(pinned=False) == MIN_HISTORY_LIMIT
    kept = {entry.text for entry in repository.list_entries()}
    assert {"keep one", "keep two"} <= kept
    assert len(kept) == MIN_HISTORY_LIMIT + 2


def test_raised_limit_does_not_delete_anything(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
) -> None:
    _capture(fake_clipboard, "first", "second")

    assert window.apply_history_limit(900) is True
    qapp.processEvents()

    assert repository.count() == 2
    assert repository.history_limit == 900
    assert "900 unpinned snippets" in window.notification.message


def test_out_of_range_limits_are_rejected(
    window: MainWindow, qapp, repository: ClipboardRepository
) -> None:
    _open_settings(window, qapp)
    page = window.settings_page

    for value in (0, MIN_HISTORY_LIMIT - 1, MAX_HISTORY_LIMIT + 1, -50):
        assert window.apply_history_limit(value) is False
        assert page.limit_error.isHidden() is False
        assert "between" in page.limit_error.text()

    assert repository.history_limit == 500
    assert page.limit_input.value() == 500


def _unavailable(*args, **kwargs):
    """Stand in for a repository whose storage is no longer reachable."""
    raise StorageError("database is locked")


def test_storage_failure_is_not_reported_as_invalid_input(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    preferences: Preferences,
    monkeypatch,
) -> None:
    limit_before = repository.history_limit
    _open_settings(window, qapp)
    page = window.settings_page
    page.limit_input.setValue(MIN_HISTORY_LIMIT)
    monkeypatch.setattr(repository, "set_history_limit", _unavailable)

    page.apply_limit_button.click()
    qapp.processEvents()

    # A database failure is not user input, so the limit field stays clean.
    assert page.limit_error.isHidden() is True
    assert page.limit_error.text() == ""
    # The operational error appears in the window's error area instead.
    assert window.notification.severity == "error"
    assert window.notification.message.startswith(
        "Could not apply the history limit"
    )
    assert "database is locked" in window.notification.message
    assert "database is locked" in window.statusBar().currentMessage()
    # Nothing claims the setting was applied, and nothing was persisted.
    assert "History limit set" not in window.notification.message
    assert repository.history_limit == limit_before
    assert preferences.history_limit() == limit_before


def test_operational_failure_clears_a_stale_validation_message(
    window: MainWindow, qapp, repository: ClipboardRepository, monkeypatch
) -> None:
    _open_settings(window, qapp)
    page = window.settings_page
    assert window.apply_history_limit(0) is False
    assert page.limit_error.isHidden() is False

    monkeypatch.setattr(repository, "set_history_limit", _unavailable)
    assert window.apply_history_limit(MIN_HISTORY_LIMIT) is False

    assert page.limit_error.isHidden() is True
    assert window.notification.severity == "error"
    assert "database is locked" in window.notification.message


def test_invalid_limit_stays_a_field_error(window: MainWindow, qapp) -> None:
    _open_settings(window, qapp)
    page = window.settings_page

    assert window.apply_history_limit(MAX_HISTORY_LIMIT + 1) is False

    assert page.limit_error.isHidden() is False
    assert "between" in page.limit_error.text()
    # Validation is not an operational failure.
    assert window.notification.message == ""


def test_a_successful_limit_clears_the_validation_message(
    window: MainWindow, qapp
) -> None:
    _open_settings(window, qapp)
    page = window.settings_page

    window.apply_history_limit(MIN_HISTORY_LIMIT - 1)
    assert page.limit_error.isHidden() is False

    assert window.apply_history_limit(MIN_HISTORY_LIMIT) is True
    assert page.limit_error.isHidden() is True


def test_the_spin_box_is_bounded_to_the_supported_range(
    window: MainWindow,
) -> None:
    page = window.settings_page

    page.limit_input.setValue(1)
    assert page.limit_input.value() == MIN_HISTORY_LIMIT

    page.limit_input.setValue(MAX_HISTORY_LIMIT + 5_000)
    assert page.limit_input.value() == MAX_HISTORY_LIMIT


def test_saved_limit_is_used_by_the_repository_at_startup(
    qapp, preferences: Preferences, tmp_path: Path
) -> None:
    preferences.set_history_limit(120)

    repository = create_repository(
        tmp_path / "startup.db", history_limit=preferences.history_limit()
    )

    assert repository.history_limit == 120


# ------------------------------------------------------------ age expiry


def test_age_expiry_is_off_by_default(window: MainWindow, qapp) -> None:
    _open_settings(window, qapp)
    page = window.settings_page

    assert page.expiry_check.isChecked() is False
    assert page.expiry_days_input.isEnabled() is False


def test_enabling_age_expiry_removes_old_unpinned_snippets(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    preferences: Preferences,
) -> None:
    _open_settings(window, qapp)
    page = window.settings_page
    now = datetime.now(timezone.utc)
    repository.add("ancient", created_at=now - timedelta(days=90))
    pinned = repository.add("kept pinned", created_at=now - timedelta(days=90))
    repository.set_pinned(pinned.id, True)
    repository.add("recent", created_at=now - timedelta(days=3))

    page.expiry_check.setChecked(True)
    page.expiry_days_input.setValue(30)
    page.apply_expiry_button.click()
    qapp.processEvents()

    assert preferences.retention_days() == 30
    assert repository.retention_days == 30
    assert sorted(entry.text for entry in repository.list_entries()) == [
        "kept pinned",
        "recent",
    ]
    assert "older than 30 days removed" in window.notification.message


def test_toggling_the_box_alone_does_not_change_storage(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    preferences: Preferences,
) -> None:
    _open_settings(window, qapp)
    page = window.settings_page
    old = repository.add(
        "old snippet", created_at=datetime.now(timezone.utc) - timedelta(days=400)
    )

    page.expiry_check.setChecked(True)
    qapp.processEvents()

    assert page.expiry_days_input.isEnabled() is True
    assert preferences.retention_days() is None
    assert repository.retention_days is None
    assert repository.get(old.id) is not None


def test_disabling_age_expiry_keeps_everything(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    preferences: Preferences,
) -> None:
    _open_settings(window, qapp)
    page = window.settings_page
    old = repository.add(
        "ancient but wanted",
        created_at=datetime.now(timezone.utc) - timedelta(days=400),
    )

    page.expiry_check.setChecked(False)
    page.apply_expiry_button.click()
    qapp.processEvents()

    assert preferences.retention_days() is None
    assert repository.retention_days is None
    assert repository.get(old.id) is not None
    assert "off" in window.notification.message.lower()


def test_saved_expiry_is_used_by_the_repository_at_startup(
    qapp, preferences: Preferences, tmp_path: Path
) -> None:
    preferences.set_retention_days(14)

    repository = create_repository(
        tmp_path / "startup-expiry.db",
        history_limit=preferences.history_limit(),
        retention_days=preferences.retention_days(),
    )

    assert repository.retention_days == 14


# ------------------------------------------------------------------ privacy


def test_privacy_section_describes_local_storage_only(
    window: MainWindow, qapp, repository: ClipboardRepository
) -> None:
    _open_settings(window, qapp)
    page = window.settings_page

    assert str(repository.database_path) == page.storage_label.text()
    assert "best-effort filter" in page.privacy_note.text()
    assert "does not detect" not in page.privacy_note.text()

    card_text = " ".join(
        label.text()
        for label in page.findChildren(type(page.privacy_note))
        if label.text()
    ).lower()
    assert "local" in card_text
    assert "no telemetry" in card_text
    assert "cloud sync" not in card_text.replace("no cloud sync", "")
    assert "account" in card_text


def test_privacy_section_states_the_real_protection_state(
    window: MainWindow, qapp, repository: ClipboardRepository
) -> None:
    _open_settings(window, qapp)
    note = window.settings_page.encryption_note.text()

    if repository.protector.is_encrypted:
        assert "Windows DPAPI" in note
        assert "unencrypted" not in note
    else:
        assert "stored unencrypted" in note


def test_privacy_section_explains_encryption_when_enabled(window: MainWindow) -> None:
    window.settings_page.set_encryption(True)

    note = window.settings_page.encryption_note.text()
    assert "encrypted at rest" in note
    assert "this Windows account" in note


def test_privacy_section_never_claims_encryption_without_it(
    window: MainWindow,
) -> None:
    window.settings_page.set_encryption(False)

    note = window.settings_page.encryption_note.text().lower()
    assert "stored unencrypted" in note
    assert "dpapi is not available" in note


def test_sensitive_detection_is_on_by_default(window: MainWindow, qapp) -> None:
    _open_settings(window, qapp)
    page = window.settings_page

    assert page.sensitive_check.isChecked() is True
    assert "detection is on" in page.sensitive_note.text().lower()


def test_disabling_sensitive_detection_lets_content_through(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
    preferences: Preferences,
) -> None:
    _open_settings(window, qapp)
    page = window.settings_page
    secret = "ghp_" + "canary" * 6

    page.sensitive_check.setChecked(False)
    qapp.processEvents()
    fake_clipboard.simulate_copy(secret)

    assert preferences.sensitive_detection_enabled() is False
    assert "detection is off" in page.sensitive_note.text().lower()
    assert repository.count() == 1


def test_reenabling_sensitive_detection_blocks_content_again(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
    preferences: Preferences,
) -> None:
    _open_settings(window, qapp)
    page = window.settings_page
    secret = "ghp_" + "canary" * 6

    page.sensitive_check.setChecked(False)
    qapp.processEvents()
    page.sensitive_check.setChecked(True)
    qapp.processEvents()
    fake_clipboard.simulate_copy(secret)

    assert preferences.sensitive_detection_enabled() is True
    assert repository.count() == 0


def test_sensitive_setting_is_not_written_while_syncing(
    window: MainWindow, qapp, preferences: Preferences
) -> None:
    _open_settings(window, qapp)
    service = window._clipboard  # noqa: SLF001 - test hook
    service.set_sensitive_detection(False)

    # Leave and come back: the page must re-read the service state.
    window.sidebar.buttons()["all"].click()
    qapp.processEvents()
    _open_settings(window, qapp)

    # Showing the page mirrors the service state instead of persisting a
    # change the user did not make.
    assert window.settings_page.sensitive_check.isChecked() is False
    assert preferences.sensitive_detection_enabled() is True


def test_pause_control_is_shared_by_settings_window_and_tray(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
    preferences: Preferences,
) -> None:
    service = ClipboardService(fake_clipboard, repository)
    service.start()
    tray = TrayIcon(icon=icons.icon("copy", "#ffffff", 16))
    service.paused_changed.connect(tray.set_paused)
    tray.set_paused(service.is_paused)

    try:
        # A second window keeps its own pause button in the same service state.
        other = MainWindow(
            repository=repository, clipboard_service=service, preferences=preferences
        )
        # The production wiring: the tray emits intent, the window acts on it.
        tray.pause_toggled.connect(other.toggle_monitoring)
        _open_settings(other, qapp)

        other.settings_page.pause_button.click()
        qapp.processEvents()

        assert service.is_paused is True
        assert other.pause_button.text() == "Resume"
        assert other.settings_page.pause_button.text() == "Resume monitoring"
        assert other.settings_page.pause_state_label.text().startswith(
            "Capture is paused"
        )
        assert tray.pause_action.text() == RESUME_TEXT

        # The window's own button and the tray action drive the same state.
        other.pause_button.click()
        qapp.processEvents()
        assert service.is_paused is False
        assert other.settings_page.pause_button.text() == "Pause monitoring"
        assert tray.pause_action.text() != RESUME_TEXT

        tray.pause_action.trigger()
        qapp.processEvents()
        assert service.is_paused is True
        assert other.settings_page.pause_button.text() == "Resume monitoring"

        other.set_hide_on_close(False)
        other.close()
        other.deleteLater()
    finally:
        service.stop()
        tray.hide()


def test_clear_from_settings_asks_before_deleting(
    window: MainWindow,
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
) -> None:
    _capture(fake_clipboard, "one", "two")
    _open_settings(window, qapp)

    window._confirm_clear_history = lambda unpinned, pinned: False
    window.settings_page.clear_button.click()
    qapp.processEvents()
    assert repository.count() == 2

    window._confirm_clear_history = lambda unpinned, pinned: True
    window.settings_page.clear_button.click()
    qapp.processEvents()
    assert repository.count() == 0


# ------------------------------------------------------------------- layout


def test_settings_page_fits_the_minimum_window_size(
    window: MainWindow, qapp
) -> None:
    window.resize(*MINIMUM_SIZE)
    window.show()
    _open_settings(window, qapp)

    page = window.settings_page
    assert page.isVisible() is True
    assert page.width() <= window.width() - window.sidebar.width()
    assert page.limit_input.isVisible() is True
    assert page.clear_button.isVisible() is True


@pytest.mark.parametrize("size", [MINIMUM_SIZE, (1400, 900)])
def test_wrapped_help_text_is_never_clipped(
    window: MainWindow, qapp, size: tuple[int, int]
) -> None:
    """Wrapped labels must stay as tall as their text at any window width."""
    window.resize(*size)
    window.show()
    _open_settings(window, qapp)

    page = window.settings_page
    labels = [
        label
        for label in page.findChildren(WrappedLabel)
        if label.isVisible() and label.width() > 0
    ]
    assert labels

    for label in labels:
        needed = label.heightForWidth(label.width())
        assert label.height() >= needed, label.text()


def test_settings_page_keeps_the_history_and_navigation_intact(
    window: MainWindow, qapp, fake_clipboard: FakeClipboard
) -> None:
    _capture(fake_clipboard, "survives a theme switch")

    _open_settings(window, qapp)
    window.settings_page.theme_buttons["light"].click()
    qapp.processEvents()
    assert window.content_stack.currentWidget() is window.settings_page

    window.sidebar.buttons()["all"].click()
    qapp.processEvents()

    assert window.content_stack.currentWidget() is window.history_page
    assert window.history_view.count() == 1
    assert window.history_view.rows[0].entry_id == 1


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_both_themes_style_the_settings_surfaces(
    window: MainWindow, qapp, mode: str
) -> None:
    window.apply_theme_mode(mode)
    qapp.processEvents()

    assert theme().name == mode
    assert "QPushButton#ChoiceButton:checked" in qapp.styleSheet()
    assert "QSpinBox#HistoryLimitInput" in qapp.styleSheet()
