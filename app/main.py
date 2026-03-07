"""
Entry point for the Pikud Haoref → Slack daemon.

Usage:
  python -m app.main run          # Start the daemon
  python -m app.main status       # Print local status JSON
  python -m app.main print-last   # Pretty-print last alert summary
  python -m app.main test-slack   # Send a test Slack message
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

from app.alert_log import AlertLog
from app.alert_parser import Alert, parse_alert
from app.config import get_settings
from app.dedupe_store import DedupeStore
from app.logging_config import configure_logging
from app.slack_notifier import SlackNotifier
from app.sse_listener import SSEEvent, SSEListener
from app.status_store import StatusStore
from app.web_server import Broadcaster, ConnectionLogger, run_web_server

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------


def _passes_filter(alert: Alert, settings) -> bool:  # type: ignore[type-arg]
    """Return True when the alert should be forwarded to Slack."""
    if not settings.include_drills and alert.is_drill:
        log.debug("Dropping drill alert %s", alert.alert_id)
        return False

    city_filters = settings.city_filter_list
    region_filters = settings.region_filter_list

    if not city_filters and not region_filters:
        return True  # no filters → pass all

    all_locations = [c.strip() for c in alert.cities + alert.areas]
    if city_filters:
        if any(city in all_locations for city in city_filters):
            return True

    if region_filters:
        if any(region in alert.region for region in region_filters):
            return True

    return False


# ---------------------------------------------------------------------------
# Core daemon
# ---------------------------------------------------------------------------


class Daemon:
    def __init__(self) -> None:
        self._settings = get_settings()
        configure_logging(self._settings.log_level)
        self._dedupe = DedupeStore(
            self._settings.db_path,
            self._settings.dedupe_ttl_seconds,
        )
        self._status = StatusStore(self._settings.status_file_path)
        self._alert_log = AlertLog(self._settings.db_path)
        self._broadcaster = Broadcaster()
        self._conn_log = ConnectionLogger()
        self._slack = SlackNotifier(
            self._settings.slack_webhook_url,
            self._settings.timezone,
        )
        self._listener = SSEListener(
            primary_url=self._settings.pikud_sse_url,
            fallback_url=self._settings.pikud_sse_fallback_url,
            api_key=self._settings.pikud_api_key,
            on_event=self._handle_event,
            on_keepalive=self._handle_keepalive,
            on_connected=self._handle_connected,
            on_disconnected=self._handle_disconnected,
            on_log=self._handle_log,
        )

    # ------------------------------------------------------------------
    # SSE callbacks
    # ------------------------------------------------------------------

    def _handle_log(self, level: str, msg: str) -> None:
        self._conn_log.append(level, msg)
        self._broadcaster.push("log", self._conn_log.recent(1)[0])

    async def _handle_event(self, event: SSEEvent, endpoint: str) -> None:
        if event.event not in ("new_alert", "alert", "message"):
            log.debug("Ignoring SSE event type=%r", event.event)
            return

        log.debug("SSE event: type=%r data=%r", event.event, event.data[:200])

        alert = parse_alert(event.data)
        if alert is None:
            return

        if self._dedupe.is_duplicate(alert.alert_id):
            log.info("Duplicate alert skipped: %s", alert.alert_id)
            self._alert_log.append(
                alert_id=alert.alert_id, title=alert.title,
                cities=alert.cities, region=alert.region,
                description=alert.description, event_time=alert.event_time,
                endpoint=endpoint, slack_result="duplicate", raw=alert.raw,
            )
            self._broadcaster.push("alert", self._alert_log.recent(1)[0])
            return

        self._dedupe.mark_seen(alert.alert_id)

        if not _passes_filter(alert, self._settings):
            log.info("Alert filtered out: %s (%s)", alert.alert_id, alert.title)
            self._alert_log.append(
                alert_id=alert.alert_id, title=alert.title,
                cities=alert.cities, region=alert.region,
                description=alert.description, event_time=alert.event_time,
                endpoint=endpoint, slack_result="filtered", raw=alert.raw,
            )
            self._broadcaster.push("alert", self._alert_log.recent(1)[0])
            return

        log.info(
            "New alert: id=%s title=%r cities=%r",
            alert.alert_id,
            alert.title,
            alert.cities,
        )

        slack_ok = await asyncio.to_thread(self._slack.send_alert, alert, endpoint)
        summary = f"{alert.title} | {', '.join(alert.cities or alert.areas)}"
        self._status.mark_alert(summary, slack_ok)

        self._alert_log.append(
            alert_id=alert.alert_id, title=alert.title,
            cities=alert.cities, region=alert.region,
            description=alert.description, event_time=alert.event_time,
            endpoint=endpoint,
            slack_result="ok" if slack_ok else "error",
            raw=alert.raw,
        )
        log_entry = self._alert_log.recent(1)[0]
        self._broadcaster.push("alert", log_entry)
        self._broadcaster.push("status", self._status.get())

        if not slack_ok:
            self._status.mark_error("Slack send failed for alert " + alert.alert_id)
            self._broadcaster.push("status", self._status.get())

    def _handle_keepalive(self) -> None:
        log.debug("SSE keep-alive")
        self._status.mark_keepalive()
        self._broadcaster.push("status", self._status.get())

    def _handle_connected(self, endpoint: str) -> None:
        log.info("Connected to %s", endpoint)
        self._status.mark_connected(endpoint)
        self._status.increment_reconnect()
        self._broadcaster.push("status", self._status.get())

    def _handle_disconnected(self) -> None:
        log.info("Disconnected from SSE endpoint")
        self._status.mark_disconnected()
        self._broadcaster.push("status", self._status.get())

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self._status.mark_started()
        self._status.mark_ready()
        log.info("Pikud Haoref daemon starting…")
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._listener.run_forever())
                tg.create_task(
                    run_web_server(
                        self._settings,
                        self._status,
                        self._alert_log,
                        self._broadcaster,
                        self._conn_log,
                    )
                )
        finally:
            self._dedupe.close()
            self._alert_log.close()


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def cmd_run() -> None:
    daemon = Daemon()
    asyncio.run(daemon.run())


def cmd_status() -> None:
    settings = get_settings()
    store = StatusStore(settings.status_file_path)
    data = store.read_from_disk()
    if not data:
        print("No status file found. Have you started the daemon?")
        sys.exit(1)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_print_last() -> None:
    settings = get_settings()
    store = StatusStore(settings.status_file_path)
    data = store.read_from_disk()
    summary = data.get("last_alert_summary")
    if summary:
        print("Last alert:", summary)
        print("At:", data.get("last_alert_at"))
        print("Slack result:", data.get("last_slack_result"))
    else:
        print("No alerts recorded yet.")


def cmd_test_slack() -> None:
    configure_logging("INFO")
    settings = get_settings()
    notifier = SlackNotifier(settings.slack_webhook_url, settings.timezone)
    ok = notifier.send_test()
    if ok:
        print("Test message sent successfully!")
    else:
        print("Test message FAILED. Check logs for details.")
        sys.exit(1)


COMMANDS = {
    "run": cmd_run,
    "status": cmd_status,
    "print-last": cmd_print_last,
    "test-slack": cmd_test_slack,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python -m app.main [{' | '.join(COMMANDS)}]")
        sys.exit(1)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
