"""Deletion hardening and optional age-based expiry.

Synthetic canary strings are written to a throwaway database in ``tmp_path``
and then searched for in the raw file, so the assertions describe what actually
survives a deletion. The user's production database is never opened.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clipnest.core import storage
from clipnest.core.storage import (
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    ClipboardRepository,
    validate_retention_days,
)

CANARY = "CANARY-deletion-probe-0123456789"
PINNED_CANARY = "CANARY-pinned-probe-9876543210"


def _file_bytes(database_path: Path) -> bytes:
    return Path(database_path).read_bytes()


def _contains(database_path: Path, needle: str) -> bool:
    return needle.encode("utf-8") in _file_bytes(database_path)


# ------------------------------------------------------------- secure_delete


def test_secure_delete_is_enabled_on_the_deletion_connection(
    repository: ClipboardRepository,
) -> None:
    entry = repository.add(CANARY)

    connection = repository._connect()  # noqa: SLF001 - test hook
    try:
        assert connection.execute("PRAGMA secure_delete").fetchone()[0] in (1, 2)
        connection.execute("DELETE FROM entries WHERE id = ?", (entry.id,))
    finally:
        connection.close()


def test_successful_deletion_removes_the_text_from_the_file(
    repository: ClipboardRepository,
) -> None:
    entry = repository.add(CANARY)
    assert _contains(repository.database_path, CANARY)

    assert repository.delete(entry.id) is True

    assert _contains(repository.database_path, CANARY) is False


def test_failed_deletion_does_not_compact(
    repository: ClipboardRepository, monkeypatch
) -> None:
    compacted: list[bool] = []
    monkeypatch.setattr(repository, "compact", lambda: compacted.append(True) or True)

    assert repository.delete(999_999) is False

    assert compacted == []


def test_clearing_unpinned_history_removes_its_text_and_keeps_pinned(
    repository: ClipboardRepository,
) -> None:
    repository.add(CANARY)
    pinned = repository.add(PINNED_CANARY)
    repository.set_pinned(pinned.id, True)

    removed = repository.clear_unpinned()

    assert removed == 1
    assert _contains(repository.database_path, CANARY) is False
    assert _contains(repository.database_path, PINNED_CANARY) is True
    assert [entry.text for entry in repository.list_entries()] == [PINNED_CANARY]


def test_automatic_retention_trim_does_not_vacuum(
    tmp_path, monkeypatch
) -> None:
    repository = ClipboardRepository(tmp_path / "trim.db", history_limit=1)
    compacted: list[bool] = []
    monkeypatch.setattr(repository, "compact", lambda: compacted.append(True) or True)

    repository.add("first")
    repository.add("second")

    assert repository.count() == 1
    assert compacted == []


@pytest.mark.parametrize(
    "error", [sqlite3.OperationalError("database is locked"), OSError("disk full")]
)
def test_compaction_failure_never_breaks_a_deletion(
    repository: ClipboardRepository, monkeypatch, error
) -> None:
    entry = repository.add(CANARY)
    other = repository.add("second entry")

    def broken_vacuum() -> None:
        raise error

    monkeypatch.setattr(repository, "_vacuum", broken_vacuum)

    assert repository.delete(entry.id) is True
    assert repository.clear_unpinned() == 1
    assert repository.count() == 0
    assert other.id != entry.id


def test_compaction_reports_success(repository: ClipboardRepository) -> None:
    assert repository.compact() is True


def test_journal_sidecar_is_not_left_behind(repository: ClipboardRepository) -> None:
    entry = repository.add(CANARY)
    repository.delete(entry.id)

    journal = Path(str(repository.database_path) + "-journal")

    assert journal.exists() is False


# --------------------------------------------------------------- validation


@pytest.mark.parametrize("value", [-1, 0, MAX_RETENTION_DAYS + 1, True, "30", 2.5])
def test_invalid_retention_values_are_rejected(value) -> None:
    with pytest.raises(ValueError):
        validate_retention_days(value)


@pytest.mark.parametrize("value", [None, "", MIN_RETENTION_DAYS, MAX_RETENTION_DAYS])
def test_valid_retention_values_are_accepted(value) -> None:
    if value in (None, ""):
        assert validate_retention_days(value) is None
    else:
        assert validate_retention_days(value) == value


def test_expiry_is_disabled_by_default(repository: ClipboardRepository) -> None:
    assert repository.retention_days is None


def test_repository_rejects_an_invalid_retention_setting(tmp_path) -> None:
    with pytest.raises(ValueError):
        ClipboardRepository(tmp_path / "bad.db", retention_days=0)


# -------------------------------------------------------------------- expiry


def _fixed_now(monkeypatch, value: datetime) -> None:
    monkeypatch.setattr(storage, "_utc_now", lambda: value)


NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def test_entries_older_than_the_cutoff_are_expired(
    tmp_path, monkeypatch
) -> None:
    repository = ClipboardRepository(tmp_path / "expiry.db")
    old = repository.add("old snippet", created_at=NOW - timedelta(days=40))
    recent = repository.add("recent snippet", created_at=NOW - timedelta(days=2))
    _fixed_now(monkeypatch, NOW)

    removed = repository.set_retention_days(30)

    assert removed == 1
    assert [entry.id for entry in repository.list_entries()] == [recent.id]
    assert repository.get(old.id) is None


def test_expiry_boundary_keeps_the_exact_cutoff(tmp_path, monkeypatch) -> None:
    repository = ClipboardRepository(tmp_path / "boundary.db")
    cutoff = NOW - timedelta(days=30)
    just_old = repository.add("just too old", created_at=cutoff - timedelta(seconds=1))
    at_cutoff = repository.add("exactly at the cutoff", created_at=cutoff)
    _fixed_now(monkeypatch, NOW)

    removed = repository.expire_older_than(30)

    assert removed == 1
    assert repository.get(just_old.id) is None
    assert repository.get(at_cutoff.id) is not None


def test_expiry_never_removes_pinned_entries(tmp_path, monkeypatch) -> None:
    repository = ClipboardRepository(tmp_path / "pinned-expiry.db")
    pinned = repository.add("pinned and old", created_at=NOW - timedelta(days=400))
    repository.set_pinned(pinned.id, True)
    repository.add("unpinned and old", created_at=NOW - timedelta(days=400))
    _fixed_now(monkeypatch, NOW)

    removed = repository.set_retention_days(30)

    assert removed == 1
    assert [entry.text for entry in repository.list_entries()] == ["pinned and old"]


def test_disabling_expiry_changes_nothing(tmp_path, monkeypatch) -> None:
    repository = ClipboardRepository(tmp_path / "disabled.db")
    _fixed_now(monkeypatch, NOW)
    old = repository.add("kept for now", created_at=NOW - timedelta(days=100))

    removed = repository.set_retention_days(None)

    assert removed == 0
    assert repository.retention_days is None
    assert repository.get(old.id) is not None


def test_count_limit_still_applies_with_expiry_enabled(tmp_path, monkeypatch) -> None:
    repository = ClipboardRepository(
        tmp_path / "both.db", history_limit=2, retention_days=30
    )
    _fixed_now(monkeypatch, NOW)
    for index in range(4):
        repository.add(f"entry {index}", created_at=NOW - timedelta(hours=index))

    assert repository.count() == 2


def test_expiry_runs_after_a_successful_capture(tmp_path, monkeypatch) -> None:
    repository = ClipboardRepository(tmp_path / "capture.db", retention_days=30)
    _fixed_now(monkeypatch, NOW)
    repository.add("fresh capture", created_at=NOW)

    # A row written directly, as if it had been stored long ago, so it is not
    # expired by ``add`` before the capture under test runs.
    with repository._session() as connection:  # noqa: SLF001 - test hook
        connection.execute(
            "INSERT INTO entries (cipher, created_at, pinned) VALUES (?, ?, 0)",
            (
                repository.protector.protect("ancient snippet"),
                (NOW - timedelta(days=90)).isoformat(),
            ),
        )

    repository.add("another capture", created_at=NOW)

    texts = [entry.text for entry in repository.list_entries()]
    assert "ancient snippet" not in texts
    assert "another capture" in texts


def test_expiry_runs_at_startup(tmp_path, monkeypatch) -> None:
    _fixed_now(monkeypatch, NOW)
    repository = ClipboardRepository(tmp_path / "startup-expiry.db")
    repository.add("ancient snippet", created_at=NOW - timedelta(days=90))
    repository.add("recent snippet", created_at=NOW - timedelta(days=1))

    reopened = ClipboardRepository(tmp_path / "startup-expiry.db", retention_days=30)

    assert [entry.text for entry in reopened.list_entries()] == ["recent snippet"]


def test_future_timestamps_are_never_expired(tmp_path, monkeypatch) -> None:
    repository = ClipboardRepository(tmp_path / "future.db", retention_days=30)
    _fixed_now(monkeypatch, NOW)
    future = repository.add("clock skew", created_at=NOW + timedelta(days=400))

    removed = repository.expire_older_than(30)

    assert removed == 0
    assert repository.get(future.id) is not None


def test_future_cutoff_is_refused(tmp_path, monkeypatch) -> None:
    """A negative date delta must never delete everything."""

    class BackwardsDelta:
        def __init__(self, days: int) -> None:
            self._days = days

        def __add__(self, other):
            return other + timedelta(days=self._days)

        def __radd__(self, other):
            return other + timedelta(days=self._days)

        def __rsub__(self, other):
            return other + timedelta(days=self._days)

    repository = ClipboardRepository(tmp_path / "guard.db")
    repository.add("snippet", created_at=NOW)
    _fixed_now(monkeypatch, NOW)
    monkeypatch.setattr(storage, "timedelta", lambda days: BackwardsDelta(-days))

    assert repository.expire_older_than(30) == 0
    assert repository.count() == 1
