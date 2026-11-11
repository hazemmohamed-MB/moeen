"""SQLite connection handling and automatic schema initialization.

Design choices:
* One short-lived connection per operation (``Database.transaction()``). Events are written
  rarely (on state changes), and this makes the database safe to use from the detection
  loop and - later - from the Flask thread at the same time, with no shared connection.
* ``BEGIN IMMEDIATE`` transactions, so read-check-update sequences (e.g. status changes) are
  atomic even with two writers; ``busy_timeout`` waits briefly instead of failing.
* WAL journal mode, so readers never block the writer.
* The schema is versioned with ``PRAGMA user_version``; a database created by a newer
  version of Moeen is refused rather than silently misread.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SCHEMA_FILE = Path(__file__).with_name("schema.sql")
REQUIRED_TABLES = ("events", "event_status_log")


class DatabaseError(RuntimeError):
    """The database file cannot be opened, initialized, or is from an incompatible version."""


class Database:
    """A Moeen SQLite database file. Creating the object initializes the file if needed."""

    def __init__(self, path: Path | str, timeout_seconds: float = 5.0) -> None:
        if str(path) == ":memory:":
            raise DatabaseError("an on-disk path is required (each operation opens its own "
                                "connection, so ':memory:' would lose all data)")
        self.path = Path(path)
        self.timeout_seconds = timeout_seconds
        self.initialize()

    # ------------------------------------------------------------------ connections
    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self.path, timeout=self.timeout_seconds, isolation_level=None)
        except sqlite3.Error as exc:
            raise DatabaseError(f"cannot open database {self.path}: {exc}") from exc
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(self.timeout_seconds * 1000)}")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, start an IMMEDIATE transaction, commit or roll back, close."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Open a connection for reading only."""
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ schema
    def initialize(self) -> None:
        """Create the parent folder, the tables and indexes if missing; check the version."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DatabaseError(f"cannot create folder for {self.path}: {exc}") from exc
        conn = self._connect()
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise DatabaseError(
                    f"{self.path} uses schema version {version}, but this Moeen version only "
                    f"supports up to {SCHEMA_VERSION}. Use a newer Moeen or another database path.")
            if version < SCHEMA_VERSION:
                created = version == 0
                conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                if created:
                    log.info("Created event database %s (schema v%d)", self.path, SCHEMA_VERSION)
            conn.execute("PRAGMA journal_mode = WAL")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = [t for t in REQUIRED_TABLES if t not in tables]
            if missing:
                raise DatabaseError(f"{self.path} is missing tables {missing}; is it a Moeen database?")
        except sqlite3.DatabaseError as exc:
            raise DatabaseError(f"cannot initialize {self.path}: {exc}") from exc
        finally:
            conn.close()

    def schema_version(self) -> int:
        with self.read() as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]
