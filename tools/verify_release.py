"""Release check for the storage contract, against real Windows DPAPI.

The test suite runs the repository with an inert protector so it never touches
a developer's DPAPI keys. This script is the counterpart that runs the shipped
code path: real ``CryptProtectData``, a real SQLite file, and a disposable
directory under the OS temp location. It never opens the user's history, the
registry, or the clipboard.

Usage (from the project root, with the project virtual environment):

    .\\.venv\\Scripts\\python.exe tools\\verify_release.py [--keep]

Exit code 0 means every check passed.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipnest.core.protection import (  # noqa: E402
    DpapiTextProtector,
    PlaintextTextProtector,
    ProtectionError,
)
from clipnest.core.storage import ClipboardRepository, StorageError  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(condition: bool, label: str) -> None:
    """Record one PASS/FAIL line."""
    RESULTS.append((bool(condition), label))


class ForeignProtector:
    """A protector that cannot read this account's DPAPI blobs."""

    name = "foreign"
    is_encrypted = True

    def protect(self, text: str) -> bytes:
        raise AssertionError("must never write with a foreign protector")

    def unprotect(self, blob: bytes) -> str:
        raise ProtectionError("this profile cannot unlock the blob")


def check_protector(protector: DpapiTextProtector) -> None:
    """The injected protector really is DPAPI."""
    check(protector.name == "dpapi", "composition protector is DPAPI")
    check(protector.is_encrypted is True, "protector reports encrypted storage")


def check_round_trip(root: Path, protector: DpapiTextProtector) -> None:
    """Capture, pin, delete, reopen: text and ordering survive a restart."""
    database = root / "roundtrip" / "clipnest.db"
    repository = ClipboardRepository(database, protector=protector)
    first = repository.add("alpha snippet-7f21")
    second = repository.add("beta snippet-3c90")
    third = repository.add("gamma snippet-11aa")
    repository.set_pinned(third.id, True)
    repository.delete(first.id)
    check(repository.count() == 2, "delete removes exactly one entry")

    reopened = ClipboardRepository(database, protector=protector)
    entries = reopened.list_entries()
    check(
        [entry.text for entry in entries] == ["gamma snippet-11aa", "beta snippet-3c90"],
        "restart preserves text and pinned-first order",
    )
    check(entries[0].pinned is True, "pinned state survives restart")
    check(entries[0].id == third.id, "entry ids survive restart")
    check(
        reopened.search("BETA")[0].id == second.id,
        "search is case-insensitive over decrypted text",
    )

    raw = database.read_bytes()
    for secret in ("alpha snippet-7f21", "beta snippet-3c90", "gamma snippet-11aa"):
        check(secret.encode("utf-8") not in raw, f"no plaintext for {secret.split()[0]}")

    with sqlite3.connect(str(database)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        canary = connection.execute(
            "SELECT COUNT(*) FROM meta WHERE key = 'protector_check'"
        ).fetchone()[0]
    check(version == 2, "PRAGMA user_version reports schema 2")
    check(canary == 1, "protector canary row is present")


def check_tamper(root: Path, protector: DpapiTextProtector) -> None:
    """A modified ciphertext is refused instead of returning corrupted text."""
    database = root / "tamper" / "clipnest.db"
    repository = ClipboardRepository(database, protector=protector)
    entry = repository.add("tamper-canary-2c6a")
    with sqlite3.connect(str(database)) as connection:
        blob = connection.execute(
            "SELECT cipher FROM entries WHERE id = ?", (entry.id,)
        ).fetchone()[0]
        # Flip a byte inside the payload: DPAPI's integrity check must notice.
        middle = len(blob) // 2
        broken = bytes([blob[middle] ^ 0xFF]).join(
            [blob[:middle], blob[middle + 1 :]]
        )
        connection.execute(
            "UPDATE entries SET cipher = ? WHERE id = ?", (broken, entry.id)
        )
    try:
        ClipboardRepository(database, protector=protector).get(entry.id)
        check(False, "tampered ciphertext is rejected")
    except StorageError as exc:
        check("could not be decrypted" in str(exc), "tampered ciphertext is rejected")
        check("tamper-canary" not in str(exc), "tamper error carries no content")
    check(database.stat().st_size > 0, "database file is kept after a tamper")


def check_foreign_history(root: Path, protector: DpapiTextProtector) -> None:
    """A history encrypted by another account is refused, not replaced."""
    database = root / "foreign" / "clipnest.db"
    ClipboardRepository(database, protector=PlaintextTextProtector()).add(
        "history-owned-by-another-account"
    )
    before = database.read_bytes()
    try:
        ClipboardRepository(database, protector=ForeignProtector())
        check(False, "unreadable history is refused")
    except StorageError as exc:
        check("will not replace" in str(exc), "unreadable history is refused")
    check(database.read_bytes() == before, "refused history is byte-identical after")


def check_migration(root: Path, protector: DpapiTextProtector) -> None:
    """A plaintext v1 database becomes encrypted v2 without losing anything."""
    database = root / "legacy" / "clipnest.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    stamp = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with sqlite3.connect(str(database)) as connection:
        connection.executescript(
            """
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0
            );
            PRAGMA user_version = 1;
            """
        )
        connection.executemany(
            "INSERT INTO entries (text, created_at, pinned) VALUES (?, ?, ?)",
            [("legacy one-4b1d", stamp, 0), ("legacy two-77ee", stamp, 1)],
        )
        original = connection.execute(
            "SELECT id, text, created_at, pinned FROM entries ORDER BY id"
        ).fetchall()

    migrated = ClipboardRepository(database, protector=protector)
    entries = migrated.list_entries()
    # ``list_entries`` is pinned-first; compare against the same ordering.
    expected = sorted(
        ((row[0], row[1], row[2], bool(row[3])) for row in original),
        key=lambda row: (not row[3], row[2], row[0]),
    )
    check(
        [(entry.id, entry.text, entry.created_at.isoformat(), entry.pinned) for entry in entries]
        == expected,
        "migration preserves id, text, timestamp and pinned",
    )
    check(
        database.read_bytes().find(b"legacy one-4b1d") == -1,
        "migrated file holds no plaintext",
    )
    with sqlite3.connect(str(database)) as connection:
        check(
            connection.execute("PRAGMA user_version").fetchone()[0] == 2,
            "migrated database reports schema 2",
        )
    check(
        ClipboardRepository(database, protector=protector).count() == len(original),
        "a second open of a migrated database changes nothing",
    )


def check_retention(root: Path, protector: DpapiTextProtector) -> None:
    """Age-based expiry removes old unpinned rows only.

    The snippets are written with expiry disabled and pinned afterwards, which
    is the order a real history goes through: a pinned snippet ages past the
    limit later, it is not born expired.
    """
    database = root / "retention" / "clipnest.db"
    old = datetime.now(timezone.utc) - timedelta(days=30)
    repository = ClipboardRepository(database, protector=protector)
    repository.add("ancient-unpinned", created_at=old)
    keep = repository.add("ancient-pinned", created_at=old)
    check(repository.set_pinned(keep.id, True), "an old snippet can be pinned")
    repository.add("recent")

    ClipboardRepository(database, protector=protector, retention_days=7)
    surviving = [
        entry.text
        for entry in ClipboardRepository(database, protector=protector).list_entries()
    ]
    check("ancient-unpinned" not in surviving, "expiry removes old unpinned entries")
    check("ancient-pinned" in surviving, "expiry keeps old pinned entries")
    check("recent" in surviving, "expiry keeps recent entries")

    removed = ClipboardRepository(database, protector=protector).clear_unpinned()
    check(removed == 1, "clear-unpinned removes only unpinned entries")
    check(
        ClipboardRepository(database, protector=protector).count() == 1,
        "pinned entry survives clear-unpinned",
    )


def main() -> int:
    """Run every check in a disposable directory and report the results."""
    keep = "--keep" in sys.argv
    root = Path(tempfile.mkdtemp(prefix="clipnest-release-"))
    protector = DpapiTextProtector()
    try:
        check_protector(protector)
        check_round_trip(root, protector)
        check_tamper(root, protector)
        check_foreign_history(root, protector)
        check_migration(root, protector)
        check_retention(root, protector)
    finally:
        if keep:
            print(f"kept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)

    failures = 0
    for ok, label in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
        failures += 0 if ok else 1
    print(f"\n{len(RESULTS) - failures}/{len(RESULTS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
