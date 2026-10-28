"""Startup state: the saved pause flag and the one-time monitoring notice.

The pause state is resolved before the clipboard service starts listening, so
these tests build the same objects the application builds, in the same order,
and then look at what a copy does.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from clipnest.app import (
    create_clipboard_service,
    create_main_window,
    create_repository,
    read_startup_pause,
)
from clipnest.preferences import PAUSED_KEY, Preferences
from tests.fakes import FakeClipboard, FakeClipboardFlags


def _preferences(tmp_path: Path) -> Preferences:
    return Preferences(
        QSettings(str(tmp_path / "startup-settings.ini"), QSettings.Format.IniFormat)
    )


def _start(
    tmp_path: Path, preferences: Preferences, database: str = "startup.db"
):
    """Build the composition root pieces in the order ``app.main`` uses."""
    repository = create_repository(database_path=tmp_path / database)
    clipboard = FakeClipboard()
    paused, unreadable = read_startup_pause(preferences)
    service = create_clipboard_service(
        clipboard,
        repository,
        flags_provider=FakeClipboardFlags(),
        paused=paused,
    )
    window = create_main_window(repository, service, preferences=preferences)
    return clipboard, repository, service, window, paused, unreadable


def test_saved_pause_state_is_applied_before_monitoring_starts(
    qapp, tmp_path: Path
) -> None:
    preferences = _preferences(tmp_path)
    preferences.set_monitoring_paused(True)

    clipboard, repository, service, window, paused, unreadable = _start(
        tmp_path, preferences
    )
    service.start()
    clipboard.simulate_copy("copied while paused")

    assert (paused, unreadable) == (True, False)
    assert service.is_paused is True
    assert repository.count() == 0
    assert window.pause_button.text() == "Resume"
    assert "Monitoring paused" in window.pause_banner.message
    assert window.settings_page.pause_button.text() == "Resume monitoring"

    service.stop()
    window.close()


def test_pausing_from_the_window_is_remembered(qapp, tmp_path: Path) -> None:
    preferences = _preferences(tmp_path)
    clipboard, repository, service, window, _, _ = _start(tmp_path, preferences)
    service.start()

    window.toggle_monitoring()
    qapp.processEvents()

    assert service.is_paused is True
    assert preferences.monitoring_paused() is True
    # A fresh instance reads the same INI file, as the next launch would.
    assert _preferences(tmp_path).monitoring_paused() is True

    clipboard.simulate_copy("still not captured")
    assert repository.count() == 0

    service.stop()
    window.close()


def test_any_pause_transition_is_remembered(qapp, tmp_path: Path) -> None:
    # The paused banner's Resume action calls the service directly, so the
    # persistence must hang off the transition signal, not off the button.
    preferences = _preferences(tmp_path)
    _, _, service, window, _, _ = _start(tmp_path, preferences)
    service.start()

    service.pause()
    assert preferences.monitoring_paused() is True

    service.resume()
    assert preferences.monitoring_paused() is False

    window.close()


def test_paused_state_survives_a_restart(qapp, tmp_path: Path) -> None:
    preferences = _preferences(tmp_path)
    _, _, service, window, _, _ = _start(tmp_path, preferences)
    service.start()
    window.toggle_monitoring()
    service.stop()
    window.close()

    restarted_clipboard, restarted_repository, restarted_service, restarted_window, paused, _ = _start(
        tmp_path, _preferences(tmp_path), database="restart.db"
    )
    restarted_service.start()
    restarted_clipboard.simulate_copy("after the restart")

    assert paused is True
    assert restarted_service.is_paused is True
    assert restarted_repository.count() == 0
    assert restarted_window.pause_button.text() == "Resume"

    restarted_service.stop()
    restarted_window.close()


def test_unreadable_pause_value_starts_paused_and_is_explained(
    qapp, tmp_path: Path
) -> None:
    store = QSettings(str(tmp_path / "startup-settings.ini"), QSettings.Format.IniFormat)
    store.setValue(PAUSED_KEY, "sometimes")
    preferences = Preferences(store)

    _, _, service, window, paused, unreadable = _start(tmp_path, preferences)

    assert (paused, unreadable) == (True, True)
    assert service.is_paused is True

    window.explain_pause_state_unreadable()

    assert window.notification.severity == "warning"
    assert "could not be read" in window.notification.message
    assert "Resume" in window.notification.message

    window.close()


def test_monitoring_notice_is_shown_once(qapp, tmp_path: Path) -> None:
    preferences = _preferences(tmp_path)
    _, _, service, window, _, _ = _start(tmp_path, preferences)

    assert window.announce_monitoring_once() is True
    assert "monitoring the clipboard" in window.notification.message
    assert preferences.monitoring_notice_shown() is True
    window.close()

    _, _, later_service, later_window, _, _ = _start(
        tmp_path, _preferences(tmp_path), database="second.db"
    )
    assert later_window.announce_monitoring_once() is False
    assert later_window.notification.message == ""

    later_service.stop()
    later_window.close()


def test_monitoring_notice_waits_for_an_unpaused_start(qapp, tmp_path: Path) -> None:
    preferences = _preferences(tmp_path)
    preferences.set_monitoring_paused(True)
    _, _, service, window, _, _ = _start(tmp_path, preferences)

    assert window.announce_monitoring_once() is False
    assert preferences.monitoring_notice_shown() is False

    window.toggle_monitoring()
    assert window.announce_monitoring_once() is True
    assert preferences.monitoring_notice_shown() is True

    service.stop()
    window.close()
