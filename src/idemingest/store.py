"""SQLite-backed store.

Two tables, one invariant: a row in ``batches`` means every file of that
batch is already in ``files``. The write is wrapped in a single transaction
so a crash halfway leaves neither -- which is what makes a replay correct
rather than merely idempotent-looking.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

from idemingest.model import Batch

_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    device_id   TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    captured_at TEXT NOT NULL DEFAULT '',
    file_count  INTEGER NOT NULL,
    PRIMARY KEY (device_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS files (
    device_id   TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    name        TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    size        INTEGER NOT NULL,
    PRIMARY KEY (device_id, fingerprint, name),
    FOREIGN KEY (device_id, fingerprint)
        REFERENCES batches (device_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS failures (
    device_id   TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    reason      TEXT NOT NULL,
    PRIMARY KEY (device_id, fingerprint)
);
"""


class Store:
    """Thin persistence layer. No business rules live here."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def has_batch(self, device_id: str, fingerprint: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM batches WHERE device_id = ? AND fingerprint = ?",
            (device_id, fingerprint),
        )
        return cur.fetchone() is not None

    def failure_reason(self, device_id: str, fingerprint: str) -> str | None:
        cur = self._conn.execute(
            "SELECT reason FROM failures WHERE device_id = ? AND fingerprint = ?",
            (device_id, fingerprint),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def write_batch(self, batch: Batch) -> tuple[str, ...]:
        """Insert the batch and all its files atomically.

        ``INSERT OR IGNORE`` on the batch row makes a concurrent double-write
        lose harmlessly instead of raising; the caller still reports it as a
        duplicate because the pre-check saw no row.
        """
        with self._conn:  # one transaction; rolls back on exception
            self._conn.execute(
                "INSERT OR IGNORE INTO batches "
                "(device_id, fingerprint, captured_at, file_count) VALUES (?, ?, ?, ?)",
                (batch.device_id, batch.fingerprint, batch.captured_at, len(batch.files)),
            )
            for f in batch.files:
                self._conn.execute(
                    "INSERT OR IGNORE INTO files "
                    "(device_id, fingerprint, name, sha256, size) VALUES (?, ?, ?, ?, ?)",
                    (batch.device_id, batch.fingerprint, f.name, f.sha256, len(f.payload)),
                )
        return tuple(sorted(f.name for f in batch.files))

    def record_failure(self, device_id: str, fingerprint: str, reason: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO failures (device_id, fingerprint, reason) "
                "VALUES (?, ?, ?)",
                (device_id, fingerprint, reason),
            )

    def snapshot(self) -> dict[str, list[tuple]]:
        """Full contents, ordered. Used by tests to assert replay-equality."""
        out: dict[str, list[tuple]] = {}
        for table, order in (
            ("batches", "device_id, fingerprint"),
            ("files", "device_id, fingerprint, name"),
            ("failures", "device_id, fingerprint"),
        ):
            with closing(
                self._conn.execute(f"SELECT * FROM {table} ORDER BY {order}")
            ) as cur:
                out[table] = cur.fetchall()
        return out

    def counts(self) -> dict[str, int]:
        return {t: len(rows) for t, rows in self.snapshot().items()}
