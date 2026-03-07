"""Slack webhook notifier — Block Kit formatting."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from slack_sdk.webhook import WebhookClient
from slack_sdk.webhook.webhook_response import WebhookResponse

from app.alert_parser import Alert

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category map  {category_id: (hebrew_label, emoji)}
# ---------------------------------------------------------------------------
_CATEGORY: dict[str, tuple[str, str]] = {
    "1":  ("ירי רקטות וטילים",      "🚀"),
    "2":  ("ירי רקטות וטילים",      "🚀"),
    "3":  ("ירי רקטות וטילים",      "🚀"),
    "4":  ("ירי רקטות וטילים",      "🚀"),
    "5":  ("חדירת כלי טיס עוין",    "✈️"),
    "6":  ("חדירת כלי טיס עוין",    "✈️"),
    "7":  ("אירוע חומרים מסוכנים",  "☢️"),
    "13": ("אירוע חומרים מסוכנים",  "☢️"),
    "20": ("רעידת אדמה",             "🌍"),
    "14": ("צונאמי",                 "🌊"),
    "15": ("אדם חשוד כמחבל",        "⚠️"),
}

_DEFAULT_EMOJI = "🚨"


def _localtime(raw: str, tz_name: str = "Asia/Jerusalem") -> str:
    """Convert an epoch float string or ISO datetime string to local time."""
    if not raw:
        return "—"
    tz = ZoneInfo(tz_name)
    try:
        ts = float(raw)
        dt = datetime.fromtimestamp(ts, tz=tz)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(tz)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def _category_info(alert: Alert) -> tuple[str, str]:
    """Return (hebrew_label, emoji) for the alert's category."""
    if alert.category:
        entry = _CATEGORY.get(str(alert.category))
        if entry:
            return entry
    # Fall back to title
    return (alert.title or "התראה", _DEFAULT_EMOJI)


def _clean_instructions(instructions: str | None, title: str | None) -> str | None:
    """Return None if instructions just repeat the title."""
    if not instructions:
        return None
    if title and instructions.strip() == title.strip():
        return None
    return instructions.strip()


def build_blocks(alert: Alert, endpoint: str, tz_name: str) -> list[dict]:  # noqa: ARG001
    """Build Slack Block Kit blocks for an alert."""
    label, emoji = _category_info(alert)
    time_str = _localtime(alert.event_time, tz_name)
    instructions = _clean_instructions(
        alert.instructions or alert.description, alert.title
    )

    cities = alert.cities or []
    city_str = "، ".join(cities) if cities else "—"

    blocks: list[dict] = []

    # ── Header ──────────────────────────────────────────────
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f"{emoji} {label}", "emoji": True},
    })
    blocks.append({"type": "divider"})

    # ── Location ─────────────────────────────────────────────────────
    blocks.append({
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*מיקום:*\n{city_str}"},
        ],
    })

    # ── Instructions (only if different from title) ────────────────────
    if instructions:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*הנחיות:*\n{instructions}"},
        })

    # ── Time ─────────────────────────────────────────────────────────────
    blocks.append({
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*זמן:*\n{time_str}"},
        ],
    })

    # ── Drill badge ──────────────────────────────────────────
    if alert.is_drill:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "🔵 *תרגיל בלבד — אין סכנה אמיתית*"},
        })

    return blocks


def build_fallback_text(alert: Alert, tz_name: str) -> str:
    """Plain-text fallback shown in notifications."""
    label, emoji = _category_info(alert)
    cities = ", ".join(alert.cities or alert.areas) or "—"
    region = f" ({alert.region})" if alert.region else ""
    time_str = _localtime(alert.event_time, tz_name)
    drill = " [תרגיל]" if alert.is_drill else ""
    return f"{emoji} {label}{drill} — {cities}{region} | {time_str}"


# ---------------------------------------------------------------------------
# SlackNotifier — wraps webhook client with daemon-friendly methods
# ---------------------------------------------------------------------------

class SlackNotifier:
    """Sends formatted Slack messages via webhook."""

    def __init__(self, webhook_url: str, tz_name: str = "Asia/Jerusalem") -> None:
        self._client = WebhookClient(webhook_url)
        self._tz_name = tz_name

    def send_alert(self, alert: Alert, endpoint: str) -> bool:
        """Send an alert to Slack. Returns True on success."""
        blocks = build_blocks(alert, endpoint, self._tz_name)
        fallback = build_fallback_text(alert, self._tz_name)
        for attempt in range(3):
            try:
                response: WebhookResponse = self._client.send(
                    text=fallback,
                    blocks=blocks,
                )
                if response.status_code == 200:
                    log.info("slack_sent alert_id=%s status=200", alert.alert_id)
                    return True
                if response.status_code == 429:
                    retry_after = int((response.headers or {}).get("Retry-After", 2))
                    log.warning(
                        "slack_rate_limited alert_id=%s attempt=%d retry_in=%ds",
                        alert.alert_id, attempt + 1, retry_after,
                    )
                    time.sleep(retry_after)
                    continue
                log.error(
                    "slack_failed status=%s body=%s",
                    response.status_code,
                    response.body,
                )
                return False
            except Exception as exc:
                log.exception("slack_exception alert_id=%s error=%s", alert.alert_id, exc)
                return False
        log.error(
            "slack_failed alert_id=%s — gave up after 3 attempts (rate limited)",
            alert.alert_id,
        )
        return False

    def send_test(self) -> bool:
        """Send a clearly-marked test message to Slack."""
        time_str = _localtime(
            str(datetime.now().timestamp()), self._tz_name
        )
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🧪 הודעת בדיקה — oref-slack",
                    "emoji": True,
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": "*סטטוס:*\n✅ oref-slack פעיל ומחובר"},
                    {"type": "mrkdwn", "text": f"*זמן:*\n{time_str}"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "זוהי הודעת בדיקה בלבד. *אין התראה אמיתית.*",
                },
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "🔵 Test message — not a real alert"}
                ],
            },
        ]
        try:
            response: WebhookResponse = self._client.send(
                text="🧪 [TEST] oref-slack — test message",
                blocks=blocks,
            )
            if response.status_code == 200:
                log.info("slack_test_sent status=200")
                return True
            log.error(
                "slack_test_failed status=%s body=%s",
                response.status_code,
                response.body,
            )
            return False
        except Exception as exc:
            log.exception("slack_test_exception error=%s", exc)
            return False
