"""Tests for the SQLite clipboard repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipnest.core.storage import (
    DEFAULT_HISTORY_LIMIT,
    ClipboardRepository,
    StorageError,
    default_database_path,
)


def test_add_and_get(repository: ClipboardRepository) -> None:
    entry = repository.add("hello world")

    assert entry.id > 0
    assert entry.text == "hello world"
    assert entry.pinned is False
    assert entry.created_at.tzinfo is not None
    assert repository.get(entry.id) == entry


def test_get_missing_entry_returns_none(repository: ClipboardRepository) -> None:
    assert repository.get(999) is None


def test_default_history_limit(repository: ClipboardRepository) -> None:
    assert repository.history_limit == DEFAULT_HISTORY_LIMIT == 500


def test_list_orders_pinned_first_then_newest(
    repository: ClipboardRepository,
) -> None:
    first = repository.add("first")
    second = repository.add("second")
    third = repository.add("third")
    repository.set_pinned(first.id, True)

    assert [entry.id for entry in repository.list_entries()] == [
        first.id,
        third.id,
        second.id,
    ]


def test_list_respects_limit_and_offset(repository: ClipboardRepository) -> None:
    for index in range(5):
        repository.add(f"entry {index}")

    assert len(repository.list_entries(limit=2)) == 2
    assert len(repository.list_entries(limit=2, offset=4)) == 1


def test_search_matches_case_insensitively(repository: ClipboardRepository) -> None:
    repository.add("Hello World")
    repository.add("goodbye")

    assert [entry.text for entry in repository.search("hello")] == ["Hello World"]


def test_search_escapes_like_wildcards(repository: ClipboardRepository) -> None:
    repository.add("100% complete")
    repository.add("1000 complete")
    repository.add("a_b")
    repository.add("axb")

    assert [entry.text for entry in repository.search("100%")] == ["100% complete"]
    assert [entry.text for entry in repository.search("a_b")] == ["a_b"]


def test_search_uses_parameterized_queries(repository: ClipboardRepository) -> None:
    repository.add("safe entry")

    assert repository.search("'; DROP TABLE entries; --") == []
    assert repository.count() == 1


def test_delete_removes_entry(repository: ClipboardRepository) -> None:
    entry = repository.add("temporary")

    assert repository.delete(entry.id) is True
    assert repository.get(entry.id) is None
    assert repository.delete(entry.id) is False


def test_set_pinned_updates_entry(repository: ClipboardRepository) -> None:
    entry = repository.add("keep me")

    assert repository.set_pinned(entry.id, True) is True
    assert repository.get(entry.id).pinned is True
    assert repository.set_pinned(9999, True) is False


def test_count_filters_by_pinned(repository: ClipboardRepository) -> None:
    pinned = repository.add("pinned")
    repository.add("unpinned")
    repository.set_pinned(pinned.id, True)

    assert repository.count() == 2
    assert repository.count(pinned=True) == 1
    assert repository.count(pinned=False) == 1


def test_clear_unpinned_keeps_pinned(repository: ClipboardRepository) -> None:
    pinned = repository.add("pinned")
    repository.set_pinned(pinned.id, True)
    repository.add("unpinned one")
    repository.add("unpinned two")

    assert repository.clear_unpinned() == 2
    assert [entry.text for entry in repository.list_entries()] == ["pinned"]


def test_retention_drops_oldest_unpinned(tmp_path: Path) -> None:
    repository = ClipboardRepository(tmp_path / "retention.db", history_limit=3)

    for index in range(5):
        repository.add(f"item {index}")

    assert [entry.text for entry in repository.list_entries()] == [
        "item 4",
        "item 3",
        "item 2",
    ]


def test_retention_preserves_pinned_entries(tmp_path: Path) -> None:
    repository = ClipboardRepository(tmp_path / "pinned.db", history_limit=2)
    pinned = repository.add("pinned entry")
    repository.set_pinned(pinned.id, True)

    for index in range(4):
        repository.add(f"unpinned {index}")

    texts = [entry.text for entry in repository.list_entries()]
    assert "pinned entry" in texts
    assert repository.count(pinned=True) == 1
    assert repository.count(pinned=False) == 2
    assert repository.count() == 3


def test_latest_text_tracks_most_recent_entry(repository: ClipboardRepository) -> None:
    assert repository.latest_text() is None

    repository.add("older")
    repository.add("newer")

    assert repository.latest_text() == "newer"


def test_entries_persist_when_repository_is_reopened(tmp_path: Path) -> None:
    database_path = tmp_path / "persist.db"
    first = ClipboardRepository(database_path)
    entry = first.add("durable text")
    first.set_pinned(entry.id, True)

    reopened = ClipboardRepository(database_path)

    assert reopened.count() == 1
    assert reopened.get(entry.id).text == "durable text"
    assert reopened.get(entry.id).pinned is True


def test_default_database_path_lives_in_app_data(qapp, monkeypatch) -> None:
    # The isolation override exists for packaged-build checks; the default must
    # stay the per-user application-data location.
    monkeypatch.delenv("CLIPNEST_DATA_DIR", raising=False)
    path = default_database_path()

    assert path.name == "clipnest.db"
    assert path.parent.name == "ClipNest"
    assert Path.cwd() not in path.parents


def test_unusable_database_path_raises_storage_error(tmp_path: Path) -> None:
    # A directory can never be opened as a SQLite file.
    with pytest.raises(StorageError):
        ClipboardRepository(tmp_path)


def test_negative_history_limit_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ClipboardRepository(tmp_path / "invalid.db", history_limit=-1)


def test_set_history_limit_trims_only_unpinned_rows(tmp_path: Path) -> None:
    repository = ClipboardRepository(tmp_path / "lowered.db")
    pinned = repository.add("pinned entry")
    repository.set_pinned(pinned.id, True)
    for index in range(5):
        repository.add(f"unpinned {index}")

    removed = repository.set_history_limit(2)

    assert repository.history_limit == 2
    assert removed == 3
    assert repository.count(pinned=True) == 1
    assert repository.count(pinned=False) == 2
    assert repository.get(pinned.id).text == "pinned entry"


def test_set_history_limit_leaves_history_below_the_limit_alone(
    tmp_path: Path,
) -> None:
    repository = ClipboardRepository(tmp_path / "raised.db")
    repository.add("first")
    repository.add("second")

    assert repository.set_history_limit(1_000) == 0
    assert repository.history_limit == 1_000
    assert repository.count() == 2


def test_set_history_limit_rejects_negative_values(tmp_path: Path) -> None:
    repository = ClipboardRepository(tmp_path / "negative.db")
    repository.add("entry")

    with pytest.raises(ValueError):
        repository.set_history_limit(-1)

    assert repository.history_limit == DEFAULT_HISTORY_LIMIT
    assert repository.count() == 1
