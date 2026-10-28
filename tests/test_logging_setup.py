"""The packaged build's only diagnostics: one small, content-free log file."""

from __future__ import annotations

import logging
from pathlib import Path

from clipnest import logging_setup


def test_log_file_is_written_in_the_given_directory(tmp_path: Path) -> None:
    path = logging_setup.configure_logging(tmp_path)
    logging.getLogger("clipnest.test").info("an event with no content")

    assert path == tmp_path / logging_setup.LOG_FILENAME
    assert path is not None and path.is_file()
    assert "an event with no content" in path.read_text(encoding="utf-8")
    assert logging_setup.log_path() == path


def test_configuring_twice_keeps_one_log_file(tmp_path: Path) -> None:
    first = logging_setup.configure_logging(tmp_path / "one")
    second = logging_setup.configure_logging(tmp_path / "two")

    assert first == second
    assert not (tmp_path / "two").exists()


def test_an_unusable_directory_does_not_stop_the_application(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("a file, not a directory", encoding="utf-8")

    # A failure to log is reported and swallowed: it must never raise.
    assert logging_setup.configure_logging(blocker) is None
    assert logging_setup.log_path() is None


def test_logging_without_a_data_directory_stays_on_the_console(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(logging_setup.paths, "data_dir", lambda: None)

    assert logging_setup.configure_logging() is None
