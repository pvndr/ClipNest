"""Domain layer: clipboard capture and SQLite persistence.

``clipboard`` owns the Qt clipboard integration, ``storage`` owns all SQL. The
UI layer depends on both but never imports ``sqlite3`` or reads the clipboard
itself.
"""
