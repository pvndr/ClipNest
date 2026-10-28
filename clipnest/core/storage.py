"""SQLite persistence for the clipboard history.

Only this module knows SQL. The UI receives :class:`ClipboardEntry` values
from the repository and never touches ``sqlite3`` itself.

The database file lives in the current Windows user's application-data
directory (via :class:`QStandardPaths`), never inside the source tree. All
statements are parameterized, and every ``sqlite3`` failure is wrapped in
:class:`StorageError` so callers can react without the original exception
(or any clipboard content) leaking into logs.

Encryption at rest: schema version 2 stores every snippet in a ``cipher``
column, protected by the injected :class:`~clipnest.core.protection.TextProtector`
(Windows DPAPI in the application). A version-1 database with a plain ``text``
column is migrated in a single transaction - rows are encrypted, the table is
replaced, ``PRAGMA user_version`` becomes 2 - and a ``VACUUM`` runs after the
commit. A failed or interrupted migration rolls back and leaves the original
file untouched; nothing is silently replaced. Ciphertext cannot be matched
with ``LIKE``, so :meth:`ClipboardRepository.search` filters decrypted entries
in memory instead.

Deletion hardening: every connection enables ``PRAGMA secure_delete`` so
removed rows are overwritten in the database file instead of lingering in free
pages, and a user-requested deletion is followed by a best-effort ``VACUUM``.
That removes the content from the *active* database file; it is not forensic
erasure - backups, snapshots, and the storage device itself are outside the
application's control.

Optional age-based expiry (``retention_days``) complements the count-based
limit. It is disabled by default, never touches pinned rows, and runs at
startup and after each successful capture.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from clipnest import paths
from clipnest.core.protection import (
    PlaintextTextProtector,
    ProtectionError,
    TextProtector,
)

logger = logging.getLogger(__name__)

#: Re-exported from :mod:`clipnest.paths`, which owns the data-directory rules.
DATABASE_FILENAME = paths.DATABASE_FILENAME
APP_FOLDER_NAME = paths.APP_FOLDER_NAME
DEFAULT_HISTORY_LIMIT = 500
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3_650
SCHEMA_VERSION = 2

#: Meta row that proves the protector in use can read this history at all. It
#: is written with the same protector as the snippets, so a database copied to
#: another Windows account fails here, before any row is misread.
PROTECTOR_CHECK_KEY = "protector_check"
PROTECTOR_CHECK_VALUE = "clipnest-protector-check"

_ENTRIES_TABLE = """
CREATE TABLE IF NOT EXISTS entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cipher     BLOB    NOT NULL,
    created_at TEXT    NOT NULL,
    pinned     INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1))
);
"""

# Same shape as ``entries``; used as the migration target so the plaintext
# table is only dropped once every row has been encrypted.
_ENTRIES_MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS entries_migrating (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cipher     BLOB    NOT NULL,
    created_at TEXT    NOT NULL,
    pinned     INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1))
);
"""

_META_TABLE = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value BLOB NOT NULL
);
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_entries_created_at "
    "ON entries (created_at DESC, id DESC);",
    "CREATE INDEX IF NOT EXISTS idx_entries_pinned ON entries (pinned);",
)

_SELECT_COLUMNS = "id, cipher, created_at, pinned"
_ORDERING = "ORDER BY pinned DESC, created_at DESC, id DESC"


class StorageError(RuntimeError):
    """Raised when the clipboard database cannot be read or written."""


@dataclass(frozen=True)
class ClipboardEntry:
    """A single stored clipboard item."""

    id: int
    text: str
    created_at: datetime
    pinned: bool = False


def default_database_path() -> Path:
    """Return the on-disk location used by the application.

    The default is ``%LOCALAPPDATA%/ClipNest/clipnest.db``; see
    :func:`clipnest.paths.data_dir` for the rules, including the
    ``CLIPNEST_DATA_DIR`` override used to run a build against an isolated
    history.
    """
    path = paths.database_path()
    if path is None:
        raise StorageError("Could not locate the application data directory")
    return path


class ClipboardRepository:
    """SQLite-backed store for clipboard entries.

    A connection is opened per operation: the history is small, every call is
    short-lived, and this keeps the repository free of thread-affinity issues
    once background work is added later.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        retention_days: int | None = None,
        protector: TextProtector | None = None,
    ) -> None:
        if history_limit < 0:
            raise ValueError("history_limit must not be negative")
        self._database_path = (
            Path(database_path) if database_path is not None else default_database_path()
        )
        self._history_limit = history_limit
        self._retention_days = validate_retention_days(retention_days)
        # The composition root injects the DPAPI protector. The inert default
        # keeps direct users (and tests) away from the developer's key state.
        self._protector: TextProtector = (
            protector if protector is not None else PlaintextTextProtector()
        )
        migrated = self._initialise()
        if migrated:
            # The plaintext pages the migration replaced must not survive in
            # the file's free list.
            self.compact()
        self._expire_retention()

    @property
    def database_path(self) -> Path:
        """Location of the SQLite file backing this repository."""
        return self._database_path

    @property
    def protector(self) -> TextProtector:
        """The protector used for every stored snippet."""
        return self._protector

    @property
    def history_limit(self) -> int:
        """Maximum number of *unpinned* entries kept on disk."""
        return self._history_limit

    @property
    def retention_days(self) -> int | None:
        """Age limit for unpinned entries, or ``None`` when expiry is off."""
        return self._retention_days

    def set_history_limit(self, history_limit: int) -> int:
        """Change the retention limit and trim immediately.

        The new limit only applies to unpinned entries: pinned rows are neither
        counted nor removed, exactly as in :meth:`enforce_retention`. Returns
        the number of rows the change removed.
        """
        if history_limit < 0:
            raise ValueError("history_limit must not be negative")
        self._history_limit = history_limit
        return self.enforce_retention()

    def set_retention_days(self, days: int | None) -> int:
        """Change the age limit and expire immediately.

        ``None`` disables age-based expiry and leaves the count-based limit
        untouched. Returns the number of rows the change removed.
        """
        self._retention_days = validate_retention_days(days)
        return self._expire_retention()

    # ---------------------------------------------------------------- writes

    def add(self, text: str, created_at: datetime | None = None) -> ClipboardEntry:
        """Insert ``text`` and apply the retention limit, returning the new entry."""
        timestamp = created_at or _utc_now()
        ciphertext = self._protect(text)
        with self._session() as connection:
            cursor = connection.execute(
                "INSERT INTO entries (cipher, created_at, pinned) VALUES (?, ?, 0)",
                (ciphertext, timestamp.isoformat()),
            )
            entry_id = int(cursor.lastrowid or 0)
        self.enforce_retention()
        self._expire_retention()
        return ClipboardEntry(
            id=entry_id, text=text, created_at=timestamp, pinned=False
        )

    def delete(self, entry_id: int) -> bool:
        """Delete one entry. Returns ``False`` when the id does not exist.

        A successful deletion is followed by a best-effort compaction so the
        removed text does not survive in the database file's free pages.
        """
        with self._session() as connection:
            cursor = connection.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            deleted = cursor.rowcount > 0
        if deleted:
            self.compact()
        return deleted

    def set_pinned(self, entry_id: int, pinned: bool) -> bool:
        """Pin or unpin one entry. Returns ``False`` when the id does not exist."""
        with self._session() as connection:
            cursor = connection.execute(
                "UPDATE entries SET pinned = ? WHERE id = ?",
                (1 if pinned else 0, entry_id),
            )
            return cursor.rowcount > 0

    def clear_unpinned(self) -> int:
        """Delete every unpinned entry, preserving pinned ones."""
        with self._session() as connection:
            cursor = connection.execute("DELETE FROM entries WHERE pinned = 0")
            removed = max(cursor.rowcount, 0)
        if removed:
            self.compact()
        return removed

    def enforce_retention(self) -> int:
        """Drop the oldest unpinned entries beyond the history limit.

        Pinned entries are never counted against the limit and are never
        deleted. Returns the number of rows removed.
        """
        with self._session() as connection:
            cursor = connection.execute(
                """
                DELETE FROM entries
                WHERE pinned = 0
                  AND id NOT IN (
                      SELECT id FROM entries
                      WHERE pinned = 0
                      ORDER BY created_at DESC, id DESC
                      LIMIT ?
                  )
                """,
                (self._history_limit,),
            )
            return max(cursor.rowcount, 0)

    def expire_older_than(self, days: int) -> int:
        """Delete unpinned entries older than ``days`` and return the count.

        Pinned entries are never expired. The cutoff is computed once, in UTC,
        and compared against the stored ISO-8601 timestamps, which are written
        in UTC by :meth:`add`.
        """
        return self._expire_retention(validate_retention_days(days))

    def compact(self) -> bool:
        """Reclaim deleted pages. Best effort: never raises.

        ``VACUUM`` runs outside any transaction, on its own connection. A
        locked database, a read-only file, or a full disk is logged and
        reported as ``False`` instead of interrupting the application.
        """
        try:
            self._vacuum()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Database compaction did not run: %s", exc)
            return False
        return True

    def _vacuum(self) -> None:
        """Run ``VACUUM`` on a fresh connection (never inside a session)."""
        with closing(self._connect()) as connection:
            if connection.in_transaction:
                return
            connection.execute("VACUUM")

    def _expire_retention(self, days: int | None = None) -> int:
        """Apply the age limit with the given or configured number of days."""
        limit = self._retention_days if days is None else days
        if limit is None:
            return 0
        now = _utc_now()
        cutoff = now - timedelta(days=limit)
        if cutoff > now:  # impossible for a positive limit; never delete anyway
            logger.warning("Retention cutoff is in the future; expiry skipped")
            return 0
        with self._session() as connection:
            cursor = connection.execute(
                "DELETE FROM entries WHERE pinned = 0 AND created_at < ?",
                (cutoff.isoformat(),),
            )
            return max(cursor.rowcount, 0)

    # ---------------------------------------------------------------- reads

    def get(self, entry_id: int) -> ClipboardEntry | None:
        """Return a single entry, or ``None`` if it no longer exists."""
        with self._session() as connection:
            row = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM entries WHERE id = ?", (entry_id,)
            ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def list_entries(
        self, limit: int | None = None, offset: int = 0
    ) -> list[ClipboardEntry]:
        """Return entries pinned first, then newest first."""
        with self._session() as connection:
            rows = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM entries {_ORDERING} "
                "LIMIT ? OFFSET ?",
                (-1 if limit is None else limit, offset),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def search(self, query: str, limit: int | None = None) -> list[ClipboardEntry]:
        """Return entries whose text contains ``query`` (case-insensitive).

        Stored snippets are ciphertext, so this decrypts the history in memory
        and filters it there. The history is bounded by the configured limit,
        which keeps the cost proportional to what is already displayed. The
        query is compared literally, so ``%`` and ``_`` have no special meaning.
        """
        needle = query.casefold()
        matches: list[ClipboardEntry] = []
        for entry in self.list_entries():
            if needle not in entry.text.casefold():
                continue
            matches.append(entry)
            if limit is not None and len(matches) >= limit:
                break
        return matches

    def count(self, pinned: bool | None = None) -> int:
        """Count all entries, or only pinned/unpinned ones when filtered."""
        sql = "SELECT COUNT(*) FROM entries"
        params: tuple[object, ...] = ()
        if pinned is not None:
            sql += " WHERE pinned = ?"
            params = (1 if pinned else 0,)
        with self._session() as connection:
            row = connection.execute(sql, params).fetchone()
        return int(row[0]) if row is not None else 0

    def latest_text(self) -> str | None:
        """Return the most recent stored text, used to seed duplicate detection."""
        with self._session() as connection:
            row = connection.execute(
                "SELECT cipher FROM entries ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._unprotect(row["cipher"], label="newest entry")

    # -------------------------------------------------------------- internals

    def _initialise(self) -> bool:
        """Create the schema or migrate a plaintext history.

        Returns ``True`` when a version-1 database was migrated. The whole
        step runs in one explicit transaction: a failure while encrypting row
        N leaves the original plaintext table exactly as it was, and the
        caller sees a :class:`StorageError` instead of a half-converted file.
        """
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(
                f"Could not create the database directory: {exc}"
            ) from exc
        migrated = False
        with closing(self._connect()) as connection:
            # Explicit transactions only: ``executescript`` (and the default
            # implicit BEGIN) would commit half of a migration.
            connection.isolation_level = None
            try:
                connection.execute("BEGIN IMMEDIATE")
                migrated = self._migrate_plaintext_entries(connection)
                self._create_schema(connection)
                self._verify_protector(connection)
                connection.execute("COMMIT")
            except (sqlite3.Error, StorageError) as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                if isinstance(exc, StorageError):
                    raise
                raise StorageError(
                    f"Could not prepare the clipboard database: {exc}"
                ) from exc
        return migrated

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(_ENTRIES_TABLE)
        connection.execute(_META_TABLE)
        for statement in _INDEXES:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _migrate_plaintext_entries(self, connection: sqlite3.Connection) -> bool:
        """Encrypt a version-1 ``text`` column in place, inside the caller's
        transaction. Returns ``False`` when the table is already encrypted.
        """
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(entries)").fetchall()
        }
        if not columns or "text" not in columns:
            return False
        logger.info("Migrating the clipboard history to encrypted storage")
        rows = connection.execute(
            "SELECT id, text, created_at, pinned FROM entries ORDER BY id"
        ).fetchall()
        connection.execute(_ENTRIES_MIGRATION_TABLE)
        for row in rows:
            plaintext = "" if row["text"] is None else str(row["text"])
            connection.execute(
                "INSERT INTO entries_migrating (id, cipher, created_at, pinned) "
                "VALUES (?, ?, ?, ?)",
                (row["id"], self._protect(plaintext), row["created_at"], row["pinned"]),
            )
        connection.execute("DROP TABLE entries")
        connection.execute("ALTER TABLE entries_migrating RENAME TO entries")
        return True

    def _verify_protector(self, connection: sqlite3.Connection) -> None:
        """Prove the injected protector can read this history, or refuse it.

        The first database written by a protector stores a protected canary.
        A later open on another Windows account fails here, before any snippet
        is misread, and the file is left alone: ClipNest never replaces a
        history it cannot unlock.
        """
        row = connection.execute(
            "SELECT value FROM meta WHERE key = ?", (PROTECTOR_CHECK_KEY,)
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                (PROTECTOR_CHECK_KEY, self._protect(PROTECTOR_CHECK_VALUE)),
            )
            return
        try:
            plain = self._protector.unprotect(bytes(row["value"]))
        except ProtectionError as exc:
            raise StorageError(
                "The saved clipboard history was encrypted by a Windows account "
                "this profile cannot unlock. ClipNest will not replace it; move "
                "the database file aside to start a new history."
            ) from exc
        if plain != PROTECTOR_CHECK_VALUE:
            raise StorageError(
                "The saved clipboard history cannot be read with the current "
                "Windows account. ClipNest will not replace it; move the "
                "database file aside to start a new history."
            )

    def _protect(self, text: str) -> bytes:
        """Encrypt one snippet, reporting failure without the text."""
        try:
            return self._protector.protect(text)
        except ProtectionError as exc:
            raise StorageError("Could not encrypt a snippet for storage") from exc

    def _unprotect(self, blob: bytes, *, label: str) -> str:
        """Decrypt one stored snippet, reporting failure without the text."""
        try:
            return self._protector.unprotect(bytes(blob))
        except ProtectionError as exc:
            raise StorageError(
                f"Stored {label} could not be decrypted. ClipNest will not "
                "replace a history it cannot read."
            ) from exc

    def _row_to_entry(self, row: sqlite3.Row) -> ClipboardEntry:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError) as exc:
            raise StorageError(
                f"Stored entry {row['id']} has an invalid timestamp"
            ) from exc
        return ClipboardEntry(
            id=int(row["id"]),
            text=self._unprotect(row["cipher"], label=f"entry {row['id']}"),
            created_at=created_at,
            pinned=bool(row["pinned"]),
        )

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(str(self._database_path), timeout=5.0)
        except sqlite3.Error as exc:
            raise StorageError(f"Could not open the clipboard database: {exc}") from exc
        connection.row_factory = sqlite3.Row
        # Every connection performs deletions, so every connection overwrites
        # deleted content instead of leaving it in free pages.
        connection.execute("PRAGMA secure_delete = ON")
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, commit on success, and translate sqlite errors."""
        try:
            with closing(self._connect()) as connection, connection:
                yield connection
        except sqlite3.Error as exc:
            raise StorageError(f"Clipboard database operation failed: {exc}") from exc


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_retention_days(value: object) -> int | None:
    """Return a valid age limit, or raise :class:`ValueError`.

    ``None`` (or an empty value) means "expiry disabled".
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("The age limit must be a whole number of days.")
    if not MIN_RETENTION_DAYS <= value <= MAX_RETENTION_DAYS:
        raise ValueError(
            f"Choose between {MIN_RETENTION_DAYS} and {MAX_RETENTION_DAYS} days."
        )
    return value
