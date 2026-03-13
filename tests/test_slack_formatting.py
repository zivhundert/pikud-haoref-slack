"""Tests for Slack message formatting and SSE frame parsing."""
import json

from app.alert_parser import Alert, parse_alert
from app.slack_notifier import build_blocks, build_fallback_text
from app.sse_listener import SSEEvent

# ---------------------------------------------------------------------------
# Slack block formatting
# ---------------------------------------------------------------------------


def _make_alert(**kwargs) -> Alert:
    defaults = dict(
        alert_id="test-001",
        title="ירי רקטות",
        cities=["תל אביב", "יפו"],
        areas=[],
        region="מרכז",
        description="נרשמו נפגעים",
        category="rockets",
        threat="",
        event_time="1700000000",
        is_drill=False,
        instructions="",
        raw={},
    )
    defaults.update(kwargs)
    return Alert(**defaults)


def test_blocks_contain_title() -> None:
    alert = _make_alert()
    blocks = build_blocks(alert, "http://localhost:8000/api/webhook/alerts", "Asia/Jerusalem")
    all_text = json.dumps(blocks, ensure_ascii=False)
    assert "ירי רקטות" in all_text


def test_blocks_contain_cities() -> None:
    alert = _make_alert()
    blocks = build_blocks(alert, "http://localhost:8000/api/webhook/alerts", "Asia/Jerusalem")
    all_text = json.dumps(blocks, ensure_ascii=False)
    assert "תל אביב" in all_text
    assert "יפו" in all_text


def test_blocks_contain_description() -> None:
    alert = _make_alert()
    blocks = build_blocks(alert, "http://localhost:8000/api/webhook/alerts", "Asia/Jerusalem")
    all_text = json.dumps(blocks, ensure_ascii=False)
    assert "נרשמו נפגעים" in all_text


def test_blocks_contain_time() -> None:
    alert = _make_alert(event_time="2024-06-01T10:00:00Z")
    blocks = build_blocks(alert, "http://localhost:8000", "Asia/Jerusalem")
    all_text = json.dumps(blocks, ensure_ascii=False)
    assert "זמן" in all_text
    assert "2024-06-01" in all_text


def test_blocks_have_header_and_section() -> None:
    alert = _make_alert()
    blocks = build_blocks(alert, "http://localhost:8000", "Asia/Jerusalem")
    types = [b["type"] for b in blocks]
    assert "header" in types
    assert "section" in types


def test_fallback_text_contains_cities() -> None:
    alert = _make_alert()
    text = build_fallback_text(alert, "Asia/Jerusalem")
    assert "תל אביב" in text
    assert "יפו" in text


def test_fallback_text_hebrew_preserved() -> None:
    alert = _make_alert(title="חדירת כלי טיס עוין", cities=["קריית שמונה"])
    text = build_fallback_text(alert, "Asia/Jerusalem")
    assert "חדירת כלי טיס עוין" in text
    assert "קריית שמונה" in text


def test_areas_used_when_cities_empty() -> None:
    alert = _make_alert(cities=[], areas=["אזור צפוני"])
    text = build_fallback_text(alert, "Asia/Jerusalem")
    assert "אזור צפוני" in text


def test_no_cities_shows_dash() -> None:
    alert = _make_alert(cities=[], areas=[])
    text = build_fallback_text(alert, "Asia/Jerusalem")
    assert "—" in text


def test_event_time_iso_converted() -> None:
    alert = _make_alert(event_time="2024-01-15T12:00:00Z")
    blocks = build_blocks(alert, "http://localhost:8000", "Asia/Jerusalem")
    all_text = json.dumps(blocks, ensure_ascii=False)
    # Should show the local Jerusalem time (UTC+2 in winter)
    assert "2024-01-15" in all_text


# ---------------------------------------------------------------------------
# SSE frame parsing (sse_listener.py logic tested inline)
# ---------------------------------------------------------------------------


def _parse_sse_text(raw_text: str) -> list[SSEEvent | None]:
    """
    Minimal SSE parser that mirrors the logic in _iter_sse_events,
    usable synchronously for tests.
    """
    events: list[SSEEvent | None] = []
    current_event = "message"
    current_data_lines: list[str] = []

    for line in raw_text.splitlines():
        if line.startswith(":"):
            events.append(None)  # keep-alive
            continue
        if not line:
            if current_data_lines:
                events.append(SSEEvent(event=current_event, data="\n".join(current_data_lines)))
            current_event = "message"
            current_data_lines = []
            continue
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current_data_lines.append(line[len("data:"):].strip())

    return events


def test_sse_new_alert_event() -> None:
    payload = {"id": "sse-1", "title": "ירי רקטות", "cities": ["חיפה"]}
    raw = (
        f"event: new_alert\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n"
        "\n"
    )
    events = _parse_sse_text(raw)
    real = [e for e in events if e is not None]
    assert len(real) == 1
    assert real[0].event == "new_alert"
    alert = parse_alert(real[0].data)
    assert alert is not None
    assert len(alert.alert_id) == 24  # always a semantic hash
    assert "חיפה" in alert.cities


def test_sse_keepalive_parsed_as_none() -> None:
    raw = ": keep-alive\n"
    events = _parse_sse_text(raw)
    assert events == [None]


def test_sse_mixed_stream() -> None:
    payload1 = {"id": "a1", "title": "t1"}
    payload2 = {"id": "a2", "title": "t2"}
    raw = (
        ": keep-alive\n"
        "\n"
        f"event: new_alert\n"
        f"data: {json.dumps(payload1)}\n"
        "\n"
        ": keep-alive\n"
        "\n"
        f"event: new_alert\n"
        f"data: {json.dumps(payload2)}\n"
        "\n"
    )
    events = _parse_sse_text(raw)
    real = [e for e in events if e is not None]
    assert len(real) == 2
    ids = [parse_alert(e.data).alert_id for e in real]  # type: ignore[union-attr]
    assert len(ids) == 2
    assert ids[0] != ids[1]  # different payloads produce different hashes
    assert all(len(i) == 24 for i in ids)


def test_sse_blank_line_without_data_no_event() -> None:
    raw = "event: new_alert\n\n"  # event line but no data line
    events = _parse_sse_text(raw)
    real = [e for e in events if e is not None]
    assert real == []
