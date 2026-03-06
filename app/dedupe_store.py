"""SQLite-backed alert deduplication store."""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_alerts (
    alert_id   TEXT PRIMARY KEY,
    first_seen REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expires ON seen_alerts (expires_at);
"""


class DedupeStore:
    def __init__(self, db_path: str = "data/alerts.db", ttl_seconds: int = 900) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_seconds
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        log.info("DedupeStore ready at %s (TTL=%ss)", path, ttl_seconds)

    # ------------------------------------------------------------------

    def is_duplicate(self, alert_id: str) -> bool:
        """Return True if alert_id was seen recently and is not yet expired."""
        now = time.time()
        row = self._conn.execute(
            "SELECT alert_id FROM seen_alerts WHERE alert_id=? AND expires_at>?",
            (alert_id, now),
        ).fetchone()
        return row is not None

    def mark_seen(self, alert_id: str) -> None:
        now = time.time()
        expires = now + self._ttl
        self._conn.execute(
            """
            INSERT INTO seen_alerts (alert_id, first_seen, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(alert_id) DO UPDATE SET expires_at=excluded.expires_at
            """,
            (alert_id, now, expires),
        )
        self._conn.commit()
        self._purge_old()

    def _purge_old(self) -> None:
        now = time.time()
        deleted = self._conn.execute(
            "DELETE FROM seen_alerts WHERE expires_at<?", (now,)
        ).rowcount
        if deleted:
            self._conn.commit()
            log.debug("Purged %d expired dedupe entries", deleted)

    def close(self) -> None:
        self._conn.close()
