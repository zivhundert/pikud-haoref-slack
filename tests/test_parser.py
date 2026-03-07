"""Tests for alert_parser.py."""
import json

from app.alert_parser import _stable_hash, parse_alert

# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------


def test_parse_full_alert() -> None:
    payload = {
        "id": "abc123",
        "title": "ירי רקטות",
        "cities": ["תל אביב", "רמת גן"],
        "region": "מרכז",
        "description": "פגיעות נרשמו",
        "event_time": "1700000000",
    }
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert alert.alert_id == "abc123"
    assert alert.title == "ירי רקטות"
    assert "תל אביב" in alert.cities
    assert alert.region == "מרכז"
    assert alert.event_time == "1700000000"


def test_parse_no_id_generates_hash() -> None:
    payload = {"title": "בדיקה", "cities": ["חיפה"]}
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert len(alert.alert_id) == 24  # sha-256 prefix


def test_parse_cities_as_string() -> None:
    payload = {"id": "x", "cities": "אשקלון"}
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert alert.cities == ["אשקלון"]


def test_parse_areas_fallback() -> None:
    payload = {"id": "y", "areas": ["צפון"]}
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert alert.areas == ["צפון"]


# ---------------------------------------------------------------------------
# Drill detection
# ---------------------------------------------------------------------------


def test_drill_detected_via_keyword_english() -> None:
    payload = {"id": "d1", "title": "drill test alert"}
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert alert.is_drill is True


def test_drill_detected_via_hebrew_keyword() -> None:
    payload = {"id": "d2", "title": "תרגיל מערכת"}
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert alert.is_drill is True


def test_real_alert_not_flagged_as_drill() -> None:
    payload = {"id": "r1", "title": "ירי רקטות", "cities": ["באר שבע"]}
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert alert.is_drill is False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_parse_invalid_json_returns_none() -> None:
    assert parse_alert("{not valid json") is None


def test_parse_non_object_returns_none() -> None:
    assert parse_alert('"just a string"') is None
    assert parse_alert("42") is None


def test_parse_empty_object_ok() -> None:
    alert = parse_alert("{}")
    assert alert is not None  # generates a hash id


# ---------------------------------------------------------------------------
# SSE frame integration – parse event data from a simulated frame
# ---------------------------------------------------------------------------


def _simulate_sse_frame(event: str, data: str) -> str:
    """Reconstruct what the SSE deserialiser would hand us."""
    # We only need the data value here; event type is tested in sse tests
    return data


def test_parse_from_sse_frame() -> None:
    """Simulate receiving event: new_alert / data: <json>."""
    raw_event_data = json.dumps(
        {
            "id": "sse-001",
            "title": "חדירת כלי טיס עוין",
            "cities": ["קריית שמונה"],
            "event_time": "1700001234",
        }
    )
    data_field = _simulate_sse_frame("new_alert", raw_event_data)
    alert = parse_alert(data_field)
    assert alert is not None
    assert alert.alert_id == "sse-001"
    assert "קריית שמונה" in alert.cities


# ---------------------------------------------------------------------------
# Stable hash consistency
# ---------------------------------------------------------------------------


def test_stable_hash_same_input() -> None:
    d = {"title": "a", "cities": ["x"]}
    assert _stable_hash(d) == _stable_hash(d)


def test_stable_hash_different_input() -> None:
    d1 = {"title": "a"}
    d2 = {"title": "b"}
    assert _stable_hash(d1) != _stable_hash(d2)


# ---------------------------------------------------------------------------
# pikud-haoref-api shaped payloads (type-string, no numeric category)
# ---------------------------------------------------------------------------


def test_type_missiles_maps_to_category_1() -> None:
    """Payloads from pikud-haoref-api use `type` not `category`."""
    payload = {
        "id": "134168709720000000",
        "type": "missiles",
        "cities": ["תל אביב"],
        "instructions": "היכנסו למרחב מוגן",
    }
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert alert.category == "1"


def test_type_hostile_aircraft_maps_to_category_5() -> None:
    payload = {
        "id": "999",
        "type": "hostileAircraftIntrusion",
        "cities": ["חיפה"],
        "instructions": "היכנסו למרחב מוגן",
    }
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert alert.category == "5"


def test_instructions_used_as_title_fallback() -> None:
    """When there is no `title`, the `instructions` field fills it."""
    payload = {
        "id": "777",
        "type": "missiles",
        "cities": ["אשדוד"],
        "instructions": "היכנסו למרחב מוגן מיד",
    }
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert alert.title == "היכנסו למרחב מוגן מיד"


def test_explicit_title_takes_precedence_over_instructions() -> None:
    payload = {
        "id": "888",
        "type": "missiles",
        "title": "ירי רקטות",
        "cities": ["באר שבע"],
        "instructions": "הנחיות אחרות",
    }
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert alert.title == "ירי רקטות"


def test_missile_drill_type_flagged_as_drill() -> None:
    payload = {
        "id": "drill-1",
        "type": "missilesDrill",
        "cities": ["נתניה"],
        "instructions": "תרגיל",
    }
    alert = parse_alert(json.dumps(payload))
    assert alert is not None
    assert alert.is_drill is True
    assert alert.category == "1"
