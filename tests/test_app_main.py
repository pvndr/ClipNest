"""The composition root's own path: build, show, run, and shut down.

``app.main`` is the only place where the real protector, the real clipboard
provider and the user's data directory meet, so it is exercised here with an
INI-backed preference store, a throwaway database and a fake clipboard.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QTimer

from clipnest import app as app_module
from clipnest.core.clipboard import ClipboardService
from clipnest.core.storage import ClipboardRepository, StorageError
from clipnest.preferences import Preferences
from tests.fakes import FakeClipboard, FakeClipboardFlags


@pytest.fixture
def isolated_preferences(tmp_path: Path, monkeypatch) -> Preferences:
    """Preferences in a throwaway INI file, never the real registry."""
    # The data directory holds the log file, so it is redirected as well: a
    # release check must not append to the user's own log.
    monkeypatch.setenv("CLIPNEST_DATA_DIR", str(tmp_path / "data"))
    prefs = Preferences(
        QSettings(str(tmp_path / "main-settings.ini"), QSettings.Format.IniFormat)
    )
    monkeypatch.setattr(app_module, "Preferences", lambda: prefs)
    return prefs


@pytest.fixture
def silent_shell(monkeypatch) -> None:
    """No tray and no icon: the run must survive without either."""
    monkeypatch.setattr(app_module, "load_app_icon", lambda: None)
    monkeypatch.setattr(app_module, "create_tray_icon", lambda icon=None: None)


@pytest.fixture
def fake_service(monkeypatch) -> dict[str, ClipboardService]:
    """Route the clipboard service to an in-memory clipboard."""
    created: dict[str, ClipboardService] = {}

    def build(clipboard, repository, **kwargs) -> ClipboardService:
        service = ClipboardService(
            FakeClipboard(),
            repository,
            flags_provider=FakeClipboardFlags(),
            sensitive_enabled=kwargs.get("sensitive_enabled", True),
            paused=kwargs.get("paused", False),
        )
        created["service"] = service
        return service

    monkeypatch.setattr(app_module, "create_clipboard_service", build)
    return created


def _quit_immediately(app) -> None:
    """Let ``main`` reach ``app.exec`` and then leave it at once."""
    QTimer.singleShot(0, app.quit)


def test_main_starts_shows_and_quits_cleanly(
    qapp, tmp_path: Path, monkeypatch, isolated_preferences, silent_shell, fake_service
) -> None:
    repository = ClipboardRepository(tmp_path / "started.db")
    monkeypatch.setattr(app_module, "create_repository", lambda **kwargs: repository)
    _quit_immediately(qapp)

    assert app_module.main([]) == 0

    # The database really was created through the composition root.
    assert repository.count() == 0
    service = fake_service["service"]
    assert service.is_running is False, "Quit must stop clipboard monitoring"

    log = tmp_path / "data" / "clipnest.log"
    assert log.is_file(), "a packaged build needs a log to diagnose a report"
    written = log.read_text(encoding="utf-8")
    assert "starting" in written
    assert "shutting down" in written
    assert "System tray" not in written


def test_main_restores_the_saved_pause_state(
    qapp, tmp_path: Path, monkeypatch, isolated_preferences, silent_shell, fake_service
) -> None:
    isolated_preferences.set_monitoring_paused(True)
    repository = ClipboardRepository(tmp_path / "paused.db")
    monkeypatch.setattr(app_module, "create_repository", lambda **kwargs: repository)
    _quit_immediately(qapp)

    assert app_module.main([]) == 0

    assert fake_service["service"].is_paused is True


def test_main_reports_an_unopenable_database_instead_of_crashing(
    qapp, monkeypatch, isolated_preferences, silent_shell
) -> None:
    def refuse(**kwargs):
        raise StorageError("The saved clipboard history cannot be read")

    monkeypatch.setattr(app_module, "create_repository", refuse)
    dialogs: list[tuple] = []
    monkeypatch.setattr(
        app_module.QMessageBox, "critical", lambda *args, **kwargs: dialogs.append(args)
    )

    assert app_module.main([]) == 1
    assert dialogs, "The failure must be shown to the user"
    message = dialogs[0][2]
    assert app_module.APP_NAME in dialogs[0][1]
    assert "could not open its clipboard database" in message
