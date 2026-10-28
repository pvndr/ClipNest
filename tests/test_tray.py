"""Tests for the system tray: menu, hide-to-tray, pause sync, and shutdown.

The tray is a thin signal emitter, so most of these tests drive it through its
real menu actions against a throwaway database and the ``FakeClipboard``. Only
the pieces that need a Windows shell (a tray that is actually available) are
faked, and the app object is stubbed where ``quit()`` would end the test run.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QSystemTrayIcon

from clipnest import app as app_module
from clipnest.app import (
    TRAY_LOST_PATIENCE,
    TrayWatchdog,
    create_tray_icon,
    quit_application,
    restore_close_to_quit,
    wire_tray,
)
from clipnest.core.clipboard import ClipboardService
from clipnest.core.storage import ClipboardRepository
from clipnest.ui import icons
from clipnest.ui import tray as tray_module
from clipnest.ui.main_window import MainWindow
from clipnest.ui.tray import (
    CLEAR_TEXT,
    PAUSE_TEXT,
    QUIT_TEXT,
    RESUME_TEXT,
    SHOW_TEXT,
    TrayIcon,
)
from tests.fakes import FakeClipboard


def _tray() -> TrayIcon:
    """Build a tray icon using an existing UI glyph, never a real shell icon."""
    return TrayIcon(icon=icons.icon("copy", "#ffffff", 16))


@pytest.fixture(autouse=True)
def restore_quit_on_last_window_closed(qapp):
    """Keep the session-wide QApplication exactly as the other tests expect."""
    original = qapp.quitOnLastWindowClosed()
    yield
    qapp.setQuitOnLastWindowClosed(original)


@pytest.fixture
def service(qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard):
    """A started clipboard service, so pause state can be observed."""
    svc = ClipboardService(clipboard=fake_clipboard, repository=repository)
    svc.start()
    yield svc
    svc.stop()


@pytest.fixture
def tray(qapp) -> TrayIcon:
    """A tray icon that is never shown, so no shell integration is required."""
    icon = _tray()
    yield icon
    icon.hide()


@pytest.fixture
def wired(qapp, repository: ClipboardRepository, service, tray):
    """A window and tray connected exactly as ``clipnest.app`` does it."""
    window = MainWindow(repository=repository, clipboard_service=service)
    wire_tray(tray, window, service, qapp)
    window.show()
    yield SimpleNamespace(window=window, service=service, tray=tray, app=qapp)
    window.set_hide_on_close(False)
    window.close()
    window.deleteLater()


# --------------------------------------------------------------- tray menu


def test_tray_menu_offers_show_pause_clear_and_quit(tray: TrayIcon) -> None:
    labels = [
        action.text() for action in tray.menu.actions() if not action.isSeparator()
    ]

    assert labels == [SHOW_TEXT, PAUSE_TEXT, CLEAR_TEXT, QUIT_TEXT]
    assert tray.contextMenu() is tray.menu


def test_tray_menu_entries_emit_their_signals(tray: TrayIcon) -> None:
    received: list[str] = []
    tray.show_requested.connect(lambda: received.append("show"))
    tray.pause_toggled.connect(lambda: received.append("pause"))
    tray.clear_requested.connect(lambda: received.append("clear"))
    tray.quit_requested.connect(lambda: received.append("quit"))

    tray.show_action.trigger()
    tray.pause_action.trigger()
    tray.clear_action.trigger()
    tray.quit_action.trigger()

    assert received == ["show", "pause", "clear", "quit"]


def test_left_click_on_the_tray_icon_requests_the_window(tray: TrayIcon) -> None:
    requests: list[bool] = []
    tray.show_requested.connect(lambda: requests.append(True))

    tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    tray.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)
    tray.activated.emit(QSystemTrayIcon.ActivationReason.Context)

    assert requests == [True, True]


def test_pause_action_label_and_tooltip_follow_the_paused_state(
    tray: TrayIcon,
) -> None:
    assert tray.pause_action.text() == PAUSE_TEXT
    assert tray.paused is False

    tray.set_paused(True)
    assert tray.pause_action.text() == RESUME_TEXT
    assert tray.paused is True
    assert "paused" in tray.toolTip()

    tray.set_paused(False)
    assert tray.pause_action.text() == PAUSE_TEXT
    assert tray.paused is False
    assert "paused" not in tray.toolTip()


def test_hidden_hint_is_announced_at_most_once(
    tray: TrayIcon, monkeypatch
) -> None:
    messages: list[tuple] = []
    monkeypatch.setattr(tray, "supportsMessages", lambda: True)
    monkeypatch.setattr(tray, "showMessage", lambda *args: messages.append(args))

    tray.notify_hidden_once()
    tray.notify_hidden_once()

    assert len(messages) == 1
    assert messages[0][0] == "ClipNest is still running"


# ------------------------------------------------------- hide and restore


def test_closing_the_window_hides_it_to_the_tray(wired) -> None:
    hidden: list[bool] = []
    wired.window.hidden_to_tray.connect(lambda: hidden.append(True))

    assert wired.window.hide_on_close is True
    assert wired.window.close() is False  # ignored: the window only hides

    assert hidden == [True]
    assert wired.window.isHidden() is True
    assert wired.app.quitOnLastWindowClosed() is False


def test_window_closes_normally_when_no_tray_is_wired(
    qapp, repository: ClipboardRepository, service
) -> None:
    window = MainWindow(repository=repository, clipboard_service=service)
    window.show()
    hidden: list[bool] = []
    window.hidden_to_tray.connect(lambda: hidden.append(True))

    assert window.hide_on_close is False
    assert window.close() is True

    assert hidden == []
    assert window.isHidden() is True
    window.deleteLater()


def test_show_action_restores_a_hidden_window(wired) -> None:
    wired.window.close()
    assert wired.window.isHidden() is True

    wired.tray.show_action.trigger()

    assert wired.window.isVisible() is True


def test_show_from_tray_clears_the_minimised_state(wired) -> None:
    wired.window.showMinimized()
    wired.window.hide()

    wired.window.show_from_tray()

    assert wired.window.isVisible() is True
    assert wired.window.isMinimized() is False


def test_monitoring_keeps_capturing_while_the_window_is_hidden(
    wired, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    wired.window.close()

    fake_clipboard.simulate_copy("captured while hidden")

    assert repository.count() == 1
    assert wired.window.history_view.count() == 1
    assert wired.service.is_running is True


# -------------------------------------------------------------- pause sync


def test_tray_pause_action_and_window_button_stay_in_sync(
    wired, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    wired.tray.pause_action.trigger()

    assert wired.service.is_paused is True
    assert wired.window.pause_button.text() == "Resume"
    assert wired.tray.pause_action.text() == RESUME_TEXT
    fake_clipboard.simulate_copy("ignored while paused")
    assert repository.count() == 0

    wired.window.pause_button.click()

    assert wired.service.is_paused is False
    assert wired.window.pause_button.text() == "Pause"
    assert wired.tray.pause_action.text() == PAUSE_TEXT
    fake_clipboard.simulate_copy("captured after resuming")
    assert repository.count() == 1


def test_tray_resume_action_ends_a_window_pause(wired) -> None:
    wired.window.pause_button.click()
    assert wired.service.is_paused is True

    wired.tray.pause_action.trigger()

    assert wired.service.is_paused is False
    assert wired.window.pause_banner.isHidden() is True
    assert wired.window.pause_button.text() == "Pause"


def test_wiring_a_paused_service_updates_the_tray_immediately(
    qapp, repository: ClipboardRepository, fake_clipboard: FakeClipboard
) -> None:
    service = ClipboardService(clipboard=fake_clipboard, repository=repository)
    service.start()
    service.pause()
    window = MainWindow(repository=repository, clipboard_service=service)
    tray = TrayIcon()

    wire_tray(tray, window, service, qapp)

    assert tray.pause_action.text() == RESUME_TEXT
    assert tray.paused is True
    assert window.pause_button.text() == "Resume"

    service.stop()
    window.deleteLater()
    tray.hide()


# ----------------------------------------------------------- clear history


def _seed_pinned_and_unpinned(
    fake_clipboard: FakeClipboard, window: MainWindow
) -> None:
    fake_clipboard.simulate_copy("keep me")
    fake_clipboard.simulate_copy("delete me")
    window.history_view.rows[-1].pin_button.click()


def test_tray_clear_asks_before_deleting(
    wired, fake_clipboard: FakeClipboard, repository: ClipboardRepository, monkeypatch
) -> None:
    _seed_pinned_and_unpinned(fake_clipboard, wired.window)
    asked: list[tuple[int, int]] = []

    def refuse(unpinned: int, pinned: int) -> bool:
        asked.append((unpinned, pinned))
        return False

    monkeypatch.setattr(wired.window, "_confirm_clear_history", refuse)

    wired.tray.clear_action.trigger()

    assert asked == [(1, 1)]
    assert repository.count() == 2


def test_tray_clear_removes_unpinned_and_keeps_pinned(
    wired, fake_clipboard: FakeClipboard, repository: ClipboardRepository, monkeypatch
) -> None:
    _seed_pinned_and_unpinned(fake_clipboard, wired.window)
    monkeypatch.setattr(wired.window, "_confirm_clear_history", lambda *args: True)

    wired.tray.clear_action.trigger()

    remaining = repository.list_entries()
    assert [entry.text for entry in remaining] == ["keep me"]
    assert remaining[0].pinned is True
    assert wired.window.history_view.count() == 1
    assert "Pinned kept" in wired.window.notification.message


def test_tray_clear_restores_a_hidden_window(
    wired, fake_clipboard: FakeClipboard, monkeypatch
) -> None:
    fake_clipboard.simulate_copy("only unpinned")
    monkeypatch.setattr(wired.window, "_confirm_clear_history", lambda *args: True)
    wired.window.close()
    assert wired.window.isHidden() is True

    wired.tray.clear_action.trigger()

    assert wired.window.isVisible() is True


def test_tray_clear_explains_when_only_pinned_remains(
    wired, fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    fake_clipboard.simulate_copy("pinned only")
    wired.window.history_view.rows[-1].pin_button.click()

    wired.tray.clear_action.trigger()

    assert repository.count() == 1
    assert wired.window.notification.message.startswith("Nothing to clear")


# --------------------------------------------------------------- shutdown


class _StubApplication:
    """Minimal QApplication stand-in that records ``quit()``."""

    def __init__(self) -> None:
        self.quit_called = False

    def quit(self) -> None:  # noqa: D401 - mirrors QApplication.quit
        self.quit_called = True


def test_quit_action_stops_clipboard_monitoring(wired) -> None:
    assert wired.service.is_running is True

    wired.tray.quit_action.trigger()

    assert wired.service.is_running is False


def test_quit_application_stops_monitoring_then_quits(
    fake_clipboard: FakeClipboard, repository: ClipboardRepository
) -> None:
    service = ClipboardService(clipboard=fake_clipboard, repository=repository)
    service.start()
    stub_app = _StubApplication()

    quit_application(stub_app, service)

    assert service.is_running is False
    assert stub_app.quit_called is True


# ------------------------------------------------------- unavailable tray


def _available_tray_shell(monkeypatch) -> None:
    """Pretend the platform reports a usable system tray."""
    monkeypatch.setattr(
        app_module,
        "QSystemTrayIcon",
        SimpleNamespace(isSystemTrayAvailable=lambda: True),
    )


def test_create_tray_icon_requires_an_icon_asset(monkeypatch) -> None:
    constructed: list[object] = []

    class _StubTray:
        def __init__(self, icon=None, parent=None) -> None:  # pragma: no cover
            constructed.append(icon)

    _available_tray_shell(monkeypatch)
    monkeypatch.setattr(app_module, "TrayIcon", _StubTray)

    # A tray without an image cannot be seen or right-clicked, so it is not
    # treated as tray support at all.
    assert create_tray_icon(None) is None
    assert constructed == []


def test_create_tray_icon_returns_none_without_tray_support(
    qapp, monkeypatch
) -> None:
    monkeypatch.setattr(
        app_module,
        "QSystemTrayIcon",
        SimpleNamespace(isSystemTrayAvailable=lambda: False),
    )

    assert create_tray_icon(icons.icon("copy", "#ffffff", 16)) is None


def test_create_tray_icon_shows_the_supplied_icon(monkeypatch) -> None:
    created: list[object] = []

    class _StubTray:
        def __init__(self, icon=None, parent=None) -> None:
            created.append(icon)
            self.visible = False
            self.hidden = False

        def show(self) -> None:
            self.visible = True

        def isVisible(self) -> bool:  # noqa: N802 - mirrors Qt
            return self.visible and not self.hidden

        def hide(self) -> None:
            self.hidden = True

    _available_tray_shell(monkeypatch)
    monkeypatch.setattr(app_module, "TrayIcon", _StubTray)
    icon = icons.icon("copy", "#ffffff", 16)

    tray = create_tray_icon(icon)

    assert isinstance(tray, _StubTray)
    assert created == [icon]
    assert tray.visible is True


def test_create_tray_icon_disables_a_tray_that_never_appears(
    qapp, monkeypatch
) -> None:
    class _InvisibleTray:
        def __init__(self, icon=None, parent=None) -> None:
            self.hidden = False

        def show(self) -> None:
            pass

        def isVisible(self) -> bool:  # noqa: N802 - mirrors Qt
            return False

        def hide(self) -> None:
            self.hidden = True

    _available_tray_shell(monkeypatch)
    monkeypatch.setattr(app_module, "TrayIcon", _InvisibleTray)

    assert create_tray_icon(icons.icon("copy", "#ffffff", 16)) is None


# ------------------------------------------------------------ tray recovery


def _report_tray_available(monkeypatch) -> None:
    """Make the module report a usable shell, leaving the tray object alone."""
    monkeypatch.setattr(
        tray_module,
        "QSystemTrayIcon",
        SimpleNamespace(isSystemTrayAvailable=lambda: True),
    )


def test_recover_reports_failure_while_the_shell_has_no_tray(
    tray: TrayIcon, monkeypatch
) -> None:
    monkeypatch.setattr(
        tray_module,
        "QSystemTrayIcon",
        SimpleNamespace(isSystemTrayAvailable=lambda: False),
    )
    shown: list[bool] = []
    monkeypatch.setattr(tray, "show", lambda: shown.append(True))

    assert tray.recover() is False
    assert shown == []


def test_recover_re_registers_the_single_icon(
    tray: TrayIcon, monkeypatch
) -> None:
    _report_tray_available(monkeypatch)
    shown: list[bool] = []
    monkeypatch.setattr(tray, "show", lambda: shown.append(True))
    monkeypatch.setattr(tray, "isVisible", lambda: True)
    requests: list[str] = []
    tray.show_requested.connect(lambda: requests.append("show"))
    actions_before = list(tray.menu.actions())

    assert tray.recover() is True
    assert tray.recover() is True

    # Recovering re-uses the one icon, its menu, and its connections.
    assert shown == [True, True]
    assert tray.menu.actions() == actions_before
    tray.show_action.trigger()
    assert requests == ["show"]


def test_watchdog_tolerates_a_brief_shell_restart(qapp) -> None:
    checks = [False, True]
    lost: list[bool] = []
    watchdog = TrayWatchdog(
        recover=lambda: checks.pop(0),
        on_lost=lambda: lost.append(True),
        patience=2,
    )
    try:
        assert watchdog.check_now() is True  # tolerated, still watching
        assert watchdog.check_now() is True  # the icon is back
        assert watchdog.gave_up is False
        assert lost == []
    finally:
        watchdog.stop()


def test_watchdog_falls_back_once_when_the_icon_stays_gone(qapp) -> None:
    lost: list[bool] = []
    watchdog = TrayWatchdog(
        recover=lambda: False,
        on_lost=lambda: lost.append(True),
        patience=TRAY_LOST_PATIENCE,
    )
    watchdog.start()
    try:
        assert watchdog.is_watching is True
        for _ in range(TRAY_LOST_PATIENCE - 1):
            assert watchdog.check_now() is True

        assert watchdog.check_now() is False

        assert lost == [True]
        assert watchdog.gave_up is True
        # Watching stops, so the fallback cannot run twice.
        assert watchdog.is_watching is False
        assert watchdog.check_now() is False
        assert lost == [True]
    finally:
        watchdog.stop()


def test_watchdog_start_keeps_a_single_timer(qapp) -> None:
    watchdog = TrayWatchdog(recover=lambda: True, on_lost=lambda: None)
    try:
        watchdog.start()
        watchdog.start()

        assert watchdog.is_watching is True
        assert len(watchdog.findChildren(QTimer)) == 1
    finally:
        watchdog.stop()


def test_wiring_returns_an_unstarted_watchdog_for_the_same_tray(
    qapp, repository: ClipboardRepository, service, tray: TrayIcon
) -> None:
    window = MainWindow(repository=repository, clipboard_service=service)
    try:
        watchdog = wire_tray(tray, window, service, qapp)

        assert isinstance(watchdog, TrayWatchdog)
        # One watchdog belongs to the one icon the tray owns.
        assert watchdog.parent() is tray
        assert watchdog.is_watching is False  # only main() starts watching
        assert watchdog.gave_up is False
    finally:
        window.set_hide_on_close(False)
        window.close()
        window.deleteLater()


def test_losing_the_tray_restores_close_to_quit(wired) -> None:
    wired.window.close()  # hidden: the tray owned the way back
    assert wired.window.isHidden() is True

    watchdog = TrayWatchdog(
        recover=lambda: False,
        on_lost=lambda: restore_close_to_quit(wired.app, wired.window),
        patience=1,
    )
    try:
        assert watchdog.check_now() is False
    finally:
        watchdog.stop()

    # Without a tray the hidden window would be stranded, so it comes back.
    assert wired.window.isVisible() is True
    assert wired.window.hide_on_close is False
    assert wired.app.quitOnLastWindowClosed() is True
    assert "tray is unavailable" in wired.window.notification.message
    assert wired.window.notification.severity == "warning"
    assert wired.window.close() is True  # a real close now, not a hide
