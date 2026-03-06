"""
Integration tests — send real Slack messages via the configured webhook.

These tests are skipped automatically when SLACK_WEBHOOK_URL is not set or
is a placeholder.  Run them explicitly:

    pytest tests/test_slack_integration.py -v
"""
from __future__ import annotations

import os
import pytest
from dotenv import load_dotenv

# Load .env so the webhook URL is available without setting env vars manually
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.alert_parser import Alert
from app.slack_notifier import SlackNotifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
_SKIP = not WEBHOOK_URL or "hooks.slack.com" not in WEBHOOK_URL

pytestmark = pytest.mark.skipif(_SKIP, reason="SLACK_WEBHOOK_URL not configured")


def _notifier() -> SlackNotifier:
    return SlackNotifier(WEBHOOK_URL, tz_name="Asia/Jerusalem")


def _alert(**kwargs) -> Alert:
    defaults = dict(
        alert_id="integ-test-001",
        title="ירי רקטות",
        cities=["תל אביב", "יפו"],
        areas=[],
        region="מרכז",
        description="הנחיות: היכנסו למרחב מוגן",
        category="1",
        threat="",
        event_time="1700000000",
        is_drill=False,
        instructions="היכנסו למרחב מוגן",
        raw={},
    )
    defaults.update(kwargs)
    return Alert(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_send_test_message() -> None:
    """send_test() — the builtin test-message helper."""
    notifier = _notifier()
    assert notifier.send_test() is True


def test_send_rocket_alert() -> None:
    """Real rocket-alert Block Kit message."""
    notifier = _notifier()
    alert = _alert(
        alert_id="integ-rockets",
        title="ירי רקטות",
        cities=["תל אביב", "רמת גן", "גבעתיים"],
        region="גוש דן",
        category="1",
        instructions="היכנסו למרחב מוגן",
    )
    assert notifier.send_alert(alert, "http://localhost:8000/api/webhook/alerts") is True


def test_send_uav_alert() -> None:
    """UAV / hostile aircraft alert."""
    notifier = _notifier()
    alert = _alert(
        alert_id="integ-uav",
        title="חדירת כלי טיס עוין",
        cities=["חיפה", "קריית אתא"],
        region="חיפה",
        category="5",
        instructions="היכנסו לממ\"ד",
    )
    assert notifier.send_alert(alert, "http://localhost:8000/api/webhook/alerts") is True


def test_send_earthquake_alert() -> None:
    """Earthquake alert."""
    notifier = _notifier()
    alert = _alert(
        alert_id="integ-earthquake",
        title="רעידת אדמה",
        cities=[],
        areas=["כל הארץ"],
        region="ארצי",
        category="20",
        instructions="",
    )
    assert notifier.send_alert(alert, "http://localhost:8000/api/webhook/alerts") is True


def test_send_drill_alert() -> None:
    """Drill alert — should show the blue drill badge."""
    notifier = _notifier()
    alert = _alert(
        alert_id="integ-drill",
        title="תרגיל מערכת",
        cities=["ירושלים"],
        region="ירושלים",
        category="1",
        is_drill=True,
        instructions="זהו תרגיל בלבד",
    )
    assert notifier.send_alert(alert, "http://localhost:8000/api/webhook/alerts") is True


def test_send_alert_no_cities() -> None:
    """Alert with no specific cities — should show em-dash."""
    notifier = _notifier()
    alert = _alert(
        alert_id="integ-nocities",
        cities=[],
        areas=[],
        region="צפון",
        instructions="",
    )
    assert notifier.send_alert(alert, "http://localhost:8000/api/webhook/alerts") is True
