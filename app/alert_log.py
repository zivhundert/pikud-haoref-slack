"""SQLite-backed log of recent alerts for the web dashboard."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_log (
    rowid       INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id    TEXT NOT NULL,
    title       TEXT,
    cities      TEXT,   -- JSON array
    region      TEXT,
    description TEXT,
    event_time  TEXT,
    received_at REAL NOT NULL,
    endpoint    TEXT,
    slack_result TEXT,  -- 'ok' | 'error' | 'filtered' | 'duplicate'
    raw         TEXT    -- JSON
);
CREATE INDEX IF NOT EXISTS idx_received ON alert_log (received_at DESC);
"""

MAX_ROWS = 100


class AlertLog:
    def __init__(self, db_path: str = "data/alerts.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------

    def append(
        self,
        *,
        alert_id: str,
        title: str,
        cities: list[str],
        region: str,
        description: str,
        event_time: str,
        endpoint: str,
        slack_result: str,
        raw: dict[str, Any],
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO alert_log
              (alert_id, title, cities, region, description,
               event_time, received_at, endpoint, slack_result, raw)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                alert_id,
                title,
                json.dumps(cities, ensure_ascii=False),
                region,
                description,
                event_time,
                time.time(),
                endpoint,
                slack_result,
                json.dumps(raw, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        self._trim()

    def recent(self, limit: int = MAX_ROWS) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM alert_log ORDER BY received_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            # Deserialise JSON columns
            try:
                d["cities"] = json.loads(d["cities"] or "[]")
            except (ValueError, TypeError):
                d["cities"] = []
            try:
                d["raw"] = json.loads(d["raw"] or "{}")
            except (ValueError, TypeError):
                d["raw"] = {}
            d["received_at_iso"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(d["received_at"])
            )
            result.append(d)
        return result

    def _trim(self) -> None:
        self._conn.execute(
            """
            DELETE FROM alert_log
            WHERE rowid NOT IN (
                SELECT rowid FROM alert_log ORDER BY received_at DESC LIMIT ?
            )
            """,
            (MAX_ROWS,),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
