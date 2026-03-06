"""Write and read a local JSON status file."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class StatusStore:
    def __init__(self, path: str = "data/status.json") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, Any] = {
            "started_at": None,
            "ready": False,
            "connected": False,
            "current_endpoint": None,
            "last_keepalive_at": None,
            "last_alert_at": None,
            "last_alert_summary": None,
            "last_slack_result": None,
            "last_error": None,
            "reconnect_count": 0,
        }

    # ------------------------------------------------------------------

    def update(self, **kwargs: Any) -> None:
        self._state.update(kwargs)
        self._write()

    def get(self) -> dict[str, Any]:
        return dict(self._state)

    def increment_reconnect(self) -> None:
        self._state["reconnect_count"] = self._state.get("reconnect_count", 0) + 1
        self._write()

    def mark_started(self) -> None:
        self._state["started_at"] = _now()
        self._write()

    def mark_ready(self) -> None:
        self._state["ready"] = True
        self._write()

    def mark_connected(self, endpoint: str) -> None:
        self._state["connected"] = True
        self._state["current_endpoint"] = endpoint
        self._write()

    def mark_disconnected(self) -> None:
        self._state["connected"] = False
        self._write()

    def mark_keepalive(self) -> None:
        self._state["last_keepalive_at"] = _now()
        self._write()

    def mark_alert(self, summary: str, slack_ok: bool) -> None:
        self._state["last_alert_at"] = _now()
        self._state["last_alert_summary"] = summary
        self._state["last_slack_result"] = "ok" if slack_ok else "error"
        self._write()

    def mark_error(self, msg: str) -> None:
        self._state["last_error"] = msg
        self._write()

    # ------------------------------------------------------------------

    def _write(self) -> None:
        try:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError as exc:
            log.warning("Could not write status file: %s", exc)

    def read_from_disk(self) -> dict[str, Any]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
