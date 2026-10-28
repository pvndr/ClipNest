"""Application-level tests: composition and persistence across restarts."""

from __future__ import annotations

from pathlib import Path

from clipnest.app import (
    create_clipboard_service,
    create_main_window,
    create_repository,
)
from tests.fakes import FakeClipboard, FakeClipboardFlags


def test_history_survives_application_restart(qapp, tmp_path: Path) -> None:
    database_path = tmp_path / "restart.db"

    repository = create_repository(database_path=database_path)
    clipboard = FakeClipboard()
    service = create_clipboard_service(
        clipboard, repository, flags_provider=FakeClipboardFlags()
    )
    window = create_main_window(repository, service)
    service.start()
    clipboard.simulate_copy("survives a restart")
    assert window.history_view.count() == 1
    service.stop()
    window.close()

    # "Restart": fresh objects, same database file.
    restarted_repository = create_repository(database_path=database_path)
    restarted_service = create_clipboard_service(
        FakeClipboard(), restarted_repository, flags_provider=FakeClipboardFlags()
    )
    restarted_window = create_main_window(restarted_repository, restarted_service)

    assert restarted_window.history_view.count() == 1
    assert restarted_repository.list_entries()[0].text == "survives a restart"
    restarted_window.close()


def test_pinned_entry_survives_restart_and_retention(qapp, tmp_path: Path) -> None:
    database_path = tmp_path / "pinned-restart.db"

    repository = create_repository(database_path=database_path, history_limit=1)
    entry = repository.add("pinned before restart")
    repository.set_pinned(entry.id, True)
    repository.add("unpinned newer")
    repository.add("unpinned newest")

    reopened = create_repository(database_path=database_path, history_limit=1)

    texts = [item.text for item in reopened.list_entries()]
    assert "pinned before restart" in texts
    assert reopened.count(pinned=True) == 1
    assert reopened.count() == 2


def test_window_renders_existing_history_on_startup(qapp, tmp_path: Path) -> None:
    database_path = tmp_path / "startup.db"
    repository = create_repository(database_path=database_path)
    repository.add("stored before launch")

    reopened = create_repository(database_path=database_path)
    service = create_clipboard_service(
        FakeClipboard(), reopened, flags_provider=FakeClipboardFlags()
    )
    window = create_main_window(reopened, service)

    assert window.history_view.count() == 1
    window.close()
