"""Tests for the data-directory rules, including the isolation override."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from clipnest import paths
from clipnest.core.storage import default_database_path
from clipnest.preferences import Preferences, default_settings


@pytest.fixture(autouse=True)
def no_override(monkeypatch) -> None:
    """Start every test from the documented default (no isolation override)."""
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)


def test_default_location_is_app_specific_and_outside_the_source_tree() -> None:
    directory = paths.data_dir()

    assert directory is not None
    assert directory.name == paths.APP_FOLDER_NAME
    assert Path.cwd() not in directory.parents
    assert paths.database_path() == directory / "clipnest.db"


def test_no_override_uses_the_platform_settings_store() -> None:
    settings = default_settings()

    assert paths.settings_path() is None
    assert settings.format() == QSettings.Format.NativeFormat


def test_absolute_override_redirects_the_database(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "isolated"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(target))

    assert paths.data_dir() == target
    # The directory is usable immediately: the database layer need not create it.
    assert target.is_dir()
    assert default_database_path() == target / "clipnest.db"


def test_override_moves_the_settings_store_into_the_directory(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "isolated"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(target))

    settings = default_settings()

    assert settings.format() == QSettings.Format.IniFormat
    assert Path(settings.fileName()) == target / paths.SETTINGS_FILENAME
    # A value written here is readable through the usual accessor and lives in
    # that file, so an isolated run cannot touch the real account's registry.
    Preferences(settings).set_theme("light")
    assert (target / paths.SETTINGS_FILENAME).is_file()
    assert Preferences(default_settings()).theme() == "light"


@pytest.mark.parametrize("value", ["", "   ", "relative/folder", "..\\outside"])
def test_relative_or_empty_override_is_ignored(value: str, monkeypatch) -> None:
    monkeypatch.setenv(paths.DATA_DIR_ENV, value)

    assert paths.data_dir_override() is None
    assert paths.data_dir() == paths.default_data_dir()
    assert paths.settings_path() is None


def test_relative_override_is_reported(caplog, monkeypatch) -> None:
    monkeypatch.setenv(paths.DATA_DIR_ENV, "relative/folder")

    with caplog.at_level("WARNING", logger=paths.__name__):
        assert paths.data_dir_override() is None

    messages = [record.getMessage() for record in caplog.records]
    assert any("absolute" in message for message in messages)
    # The rejected value itself carries no clipboard content, only a path.
    assert any("relative/folder" in message for message in messages)


def test_override_is_ignored_when_the_directory_cannot_be_created(
    tmp_path: Path, monkeypatch
) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("a file, so a child path cannot be created", encoding="utf-8")
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(blocker / "child"))

    assert paths.data_dir_override() is None
    assert paths.database_path() == paths.default_data_dir() / "clipnest.db"
