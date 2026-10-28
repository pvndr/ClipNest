"""Shared pytest fixtures for headless Qt tests."""

from __future__ import annotations

import os

# Must be set before the QApplication is created so tests run without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import logging  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from clipnest import app as app_module  # noqa: E402
from clipnest import logging_setup  # noqa: E402
from clipnest.core import clipboard_flags, protection  # noqa: E402
from clipnest.core.clipboard import ClipboardService  # noqa: E402
from clipnest.core.storage import ClipboardRepository  # noqa: E402
from clipnest.preferences import Preferences  # noqa: E402
from clipnest.ui.main_window import MainWindow  # noqa: E402
from clipnest.ui.theme import DARK, apply_theme  # noqa: E402
from tests.fakes import FakeClipboard, FakeClipboardFlags  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Provide a single QApplication instance for the whole test session."""
    app = QApplication.instance() or QApplication([])
    yield app
    app.quit()


@pytest.fixture(autouse=True)
def no_global_logging():
    """Keep every test out of the real ClipNest log file.

    ``app.main`` configures logging once per process; without this guard the
    first test that calls it would leave a handler writing to a temporary
    directory that pytest deletes afterwards, for the rest of the session.
    """
    root = logging.getLogger()
    original = root.handlers[:]
    logging_setup._configured = False
    logging_setup._configured_path = None
    yield
    for handler in root.handlers[:]:
        if handler not in original:
            root.removeHandler(handler)
            handler.close()
    logging_setup._configured = False
    logging_setup._configured_path = None


@pytest.fixture(autouse=True)
def no_native_clipboard(monkeypatch):
    """Fail loudly if a test reaches the real Win32 clipboard.

    Only a test that injects its own fake ``user32``/``kernel32`` may call
    ``WindowsClipboardFlags``; everything else must go through a fake provider,
    so the developer's own clipboard is never read.
    """
    original_load = clipboard_flags.WindowsClipboardFlags._load

    def guarded_load(self):
        if self._user32 is None and clipboard_flags.IS_WINDOWS:
            raise AssertionError(
                "Tests must not call the native clipboard; inject a fake provider"
            )
        return original_load(self)

    monkeypatch.setattr(clipboard_flags.WindowsClipboardFlags, "_load", guarded_load)


@pytest.fixture(autouse=True)
def no_native_protector(monkeypatch):
    """Tests never reach the developer's real DPAPI key material.

    ``app.create_repository`` injects :func:`default_text_protector`, which is
    DPAPI on Windows. Composing the real application in a test must not write
    to (or depend on) the account running the suite, so the composition root
    gets the inert protector unless a test injects its own explicitly.
    """
    plaintext = protection.PlaintextTextProtector()
    monkeypatch.setattr(protection, "default_text_protector", lambda: plaintext)
    monkeypatch.setattr(app_module, "default_text_protector", lambda: plaintext)


@pytest.fixture(autouse=True)
def restore_dark_theme(qapp):
    """Leave the shared application on the default theme after every test."""
    yield
    apply_theme(qapp, DARK.name)


@pytest.fixture(autouse=True)
def destroy_closed_widgets(qapp):
    """Finish ``deleteLater()`` before the next test builds its widgets.

    ``deleteLater()`` only queues deletion, and ``processEvents()`` does not
    deliver ``DeferredDelete``. Without this, every window a test closed stays
    alive for the rest of the session, and each application-wide re-polish
    (every theme change calls ``setStyle`` and ``setStyleSheet``) re-styles all
    of them: teardown grew from milliseconds to seconds as the suite ran on.
    """
    yield
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


@pytest.fixture
def preferences(tmp_path) -> Preferences:
    """Preferences in a throwaway INI file, never the real registry."""
    return Preferences(
        QSettings(str(tmp_path / "clipnest-settings.ini"), QSettings.Format.IniFormat)
    )


@pytest.fixture
def repository(tmp_path) -> ClipboardRepository:
    """A repository backed by a throwaway database, never the real one."""
    return ClipboardRepository(tmp_path / "clipnest-test.db")


@pytest.fixture
def fake_clipboard() -> FakeClipboard:
    """In-memory clipboard so tests never touch the system clipboard."""
    return FakeClipboard()


@pytest.fixture
def fake_flags() -> FakeClipboardFlags:
    """Clipboard privacy markers that report "no objection" by default."""
    return FakeClipboardFlags()


@pytest.fixture
def clipboard_service(
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
    fake_flags: FakeClipboardFlags,
) -> ClipboardService:
    """A started clipboard service wired to the fake clipboard."""
    service = ClipboardService(
        clipboard=fake_clipboard, repository=repository, flags_provider=fake_flags
    )
    service.start()
    yield service
    service.stop()


@pytest.fixture
def window(
    qapp,
    repository: ClipboardRepository,
    fake_clipboard: FakeClipboard,
    fake_flags: FakeClipboardFlags,
    preferences: Preferences,
) -> MainWindow:
    """A main window wired to the fake clipboard and a throwaway database."""
    service = ClipboardService(fake_clipboard, repository, flags_provider=fake_flags)
    service.start()
    win = MainWindow(
        repository=repository, clipboard_service=service, preferences=preferences
    )
    yield win
    service.stop()
    win.close()
    win.deleteLater()
