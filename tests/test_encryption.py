"""Encryption at rest, schema migration, and the recovery decision.

Every test injects its own protector: the developer's real DPAPI key material is
never involved (``conftest`` also keeps the composition root off it).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clipnest.app import create_clipboard_service, create_repository
from clipnest.core.storage import (
    SCHEMA_VERSION,
    ClipboardRepository,
    StorageError,
)
from tests.fakes import (
    FakeClipboard,
    FakeClipboardFlags,
    FailingProtector,
    FakeProtector,
    ForeignProtector,
)

CANARY = "encryption-canary-7d1c"
NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def _create_legacy_database(
    path: Path, rows: list[tuple[str, str, int]]
) -> None:
    """Write a version-1 database: a plaintext ``text`` column, no meta table."""
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(
            """
            CREATE TABLE entries (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                text       TEXT    NOT NULL,
                created_at TEXT    NOT NULL,
                pinned     INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1))
            );
            CREATE INDEX idx_entries_created_at
                ON entries (created_at DESC, id DESC);
            CREATE INDEX idx_entries_pinned ON entries (pinned);
            """
        )
        connection.executemany(
            "INSERT INTO entries (text, created_at, pinned) VALUES (?, ?, ?)", rows
        )
        connection.commit()
    finally:
        connection.close()


def _user_version(path: Path) -> int:
    connection = sqlite3.connect(str(path))
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()


def _raw_rows(path: Path) -> list[tuple]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute("SELECT * FROM entries ORDER BY id").fetchall()
    finally:
        connection.close()


# --------------------------------------------------------------- encryption


def test_snippets_are_never_written_as_plaintext(tmp_path: Path) -> None:
    protector = FakeProtector()
    repository = ClipboardRepository(tmp_path / "encrypted.db", protector=protector)

    entry = repository.add(CANARY)

    assert CANARY.encode("utf-8") not in repository.database_path.read_bytes()
    assert repository.get(entry.id).text == CANARY
    # The canary row is protected with the same protector as the snippets.
    assert protector.protects >= 2


def test_every_read_path_round_trips(tmp_path: Path) -> None:
    repository = ClipboardRepository(tmp_path / "reads.db", protector=FakeProtector())
    first = repository.add("first body", created_at=NOW)
    repository.add("second body", created_at=NOW + timedelta(minutes=1))

    assert repository.get(first.id).text == "first body"
    assert [entry.text for entry in repository.list_entries(limit=1)] == ["second body"]
    assert [entry.text for entry in repository.search("second")] == ["second body"]
    assert repository.latest_text() == "second body"


def test_search_is_case_insensitive_and_literal(tmp_path: Path) -> None:
    repository = ClipboardRepository(tmp_path / "search.db", protector=FakeProtector())
    for text in ("Report.PDF", "100% complete", "a_b value"):
        repository.add(text)

    assert [entry.text for entry in repository.search("report")] == ["Report.PDF"]
    assert [entry.text for entry in repository.search("%")] == ["100% complete"]
    assert [entry.text for entry in repository.search("_")] == ["a_b value"]
    assert [entry.text for entry in repository.search("A_B")] == ["a_b value"]
    assert repository.search("'; DROP TABLE entries; --") == []
    assert repository.count() == 3


def test_tampered_ciphertext_is_reported_not_hidden(tmp_path: Path) -> None:
    repository = ClipboardRepository(tmp_path / "tampered.db", protector=FakeProtector())
    entry = repository.add(CANARY)

    with repository._session() as connection:  # noqa: SLF001 - test hook
        connection.execute(
            "UPDATE entries SET cipher = ? WHERE id = ?",
            (b"fake:\xff\xfe", entry.id),
        )

    with pytest.raises(StorageError) as excinfo:
        repository.get(entry.id)

    assert "could not be decrypted" in str(excinfo.value)
    assert CANARY not in str(excinfo.value)


def test_captured_snippets_end_up_encrypted(tmp_path: Path) -> None:
    protector = FakeProtector()
    repository = create_repository(tmp_path / "capture.db", protector=protector)
    clipboard = FakeClipboard()
    service = create_clipboard_service(
        clipboard, repository, flags_provider=FakeClipboardFlags()
    )
    service.start()

    clipboard.simulate_copy(CANARY)

    assert repository.count() == 1
    assert CANARY.encode("utf-8") not in repository.database_path.read_bytes()
    service.stop()


def test_default_repository_protector_is_inert(tmp_path: Path) -> None:
    # Direct construction (tests, embedders) must not reach the real DPAPI.
    repository = ClipboardRepository(tmp_path / "default.db")

    assert repository.protector.is_encrypted is False


# ----------------------------------------------------------------- migration


def test_migration_encrypts_and_preserves_the_history(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    _create_legacy_database(
        path,
        [
            ("older plaintext", (NOW - timedelta(minutes=5)).isoformat(), 0),
            ("pinned plaintext", (NOW - timedelta(minutes=10)).isoformat(), 1),
        ],
    )
    assert b"older plaintext" in path.read_bytes()

    repository = ClipboardRepository(path, protector=FakeProtector())

    stored = path.read_bytes()
    assert b"older plaintext" not in stored
    assert b"pinned plaintext" not in stored
    entries = repository.list_entries()
    assert [entry.text for entry in entries] == ["pinned plaintext", "older plaintext"]
    assert entries[0].pinned is True
    assert {entry.id for entry in entries} == {1, 2}
    assert entries[1].created_at == NOW - timedelta(minutes=5)
    assert _user_version(path) == SCHEMA_VERSION == 2


def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "once.db"
    _create_legacy_database(path, [("only row", NOW.isoformat(), 0)])

    ClipboardRepository(path, protector=FakeProtector())
    protector = FakeProtector()
    reopened = ClipboardRepository(path, protector=protector)

    assert [entry.text for entry in reopened.list_entries()] == ["only row"]
    # No second migration: only the canary check reads through the protector.
    assert protector.protects == 0


def test_failed_migration_leaves_the_original_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "rollback.db"
    _create_legacy_database(
        path,
        [("alpha plaintext", NOW.isoformat(), 0), ("beta plaintext", NOW.isoformat(), 0)],
    )

    with pytest.raises(StorageError) as excinfo:
        ClipboardRepository(path, protector=FailingProtector(fail_after=1))

    assert "encrypt" in str(excinfo.value).lower()
    assert "alpha plaintext" not in str(excinfo.value)
    # The table was not replaced and the version was not bumped.
    assert [row[1] for row in _raw_rows(path)] == ["alpha plaintext", "beta plaintext"]
    assert _user_version(path) == 0

    # A later start with a working protector still migrates the same history.
    recovered = ClipboardRepository(path, protector=FakeProtector())
    assert [entry.text for entry in recovered.list_entries()] == [
        "beta plaintext",
        "alpha plaintext",
    ]


def test_history_from_another_key_is_refused_and_kept(tmp_path: Path) -> None:
    path = tmp_path / "foreign.db"
    ClipboardRepository(path, protector=FakeProtector()).add("written elsewhere")

    with pytest.raises(StorageError) as excinfo:
        ClipboardRepository(path, protector=ForeignProtector())

    assert "will not replace" in str(excinfo.value)
    # Nothing was deleted: the original protector still opens the history.
    reopened = ClipboardRepository(path, protector=FakeProtector())
    assert reopened.latest_text() == "written elsewhere"


def test_retention_and_pinning_survive_a_migrated_database(tmp_path: Path) -> None:
    path = tmp_path / "retained.db"
    now = datetime.now(timezone.utc)
    _create_legacy_database(
        path,
        [
            ("pinned and old", (now - timedelta(days=90)).isoformat(), 1),
            ("unpinned and old", (now - timedelta(days=90)).isoformat(), 0),
            ("unpinned and new", now.isoformat(), 0),
        ],
    )

    repository = ClipboardRepository(
        path, retention_days=30, protector=FakeProtector()
    )

    # ``retention_days`` applies at startup, as it does after a normal restart.
    assert [entry.text for entry in repository.list_entries()] == [
        "pinned and old",
        "unpinned and new",
    ]
