"""Create the disposable databases used by the packaged-build checks.

Two scenarios need a database that does not exist in a normal run:

``legacy <path>``
    A schema version 1 history: plain ``text`` column, ``PRAGMA user_version = 1``.
    Launching the application on this file exercises the real migration.

``damage-canary <path>``
    Replace the protected canary row of an existing history with bytes no DPAPI
    key can unlock. That is what a history from another Windows account looks
    like, so launching the application must refuse it instead of starting a new
    history on top of it.

Both modes only ever touch the path they are given, which should be a throwaway
directory. Usage::

    .\\.venv\\Scripts\\python.exe tools\\seed_database.py legacy <path>\\clipnest.db
    .\\.venv\\Scripts\\python.exe tools\\seed_database.py damage-canary <path>\\clipnest.db
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: Rows written by ``legacy``; ids and pinned state are chosen to prove both
#: survive the migration.
LEGACY_ROWS = ("legacy alpha-4b1d", "legacy beta-77ee", "legacy gamma-9c02")


def seed_legacy(path: Path) -> None:
    """Write a plaintext schema version 1 history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"refusing to overwrite {path}")
    stamp = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with sqlite3.connect(str(path)) as connection:
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
            [(row, stamp, 1 if index == 1 else 0) for index, row in enumerate(LEGACY_ROWS)],
        )
    print(f"legacy v1 history with {len(LEGACY_ROWS)} rows: {path}")


def damage_canary(path: Path) -> None:
    """Make the history unreadable by replacing its protected canary row."""
    if not path.is_file():
        raise SystemExit(f"no database at {path}")
    with sqlite3.connect(str(path)) as connection:
        connection.execute(
            "UPDATE meta SET value = ? WHERE key = 'protector_check'",
            (b"\x00" * 64,),
        )
        connection.commit()
    print(f"canary replaced with unusable bytes: {path}")


def main(argv: list[str]) -> int:
    """Run one mode against one path."""
    if len(argv) != 3:
        print(__doc__)
        return 2
    mode, raw_path = argv[1], Path(argv[2])
    if mode == "legacy":
        seed_legacy(raw_path)
    elif mode == "damage-canary":
        damage_canary(raw_path)
    else:
        print(f"unknown mode {mode!r}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
