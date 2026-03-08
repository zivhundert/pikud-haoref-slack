"""Parse raw SSE alert payloads into typed models."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Alert:
    """Typed representation of a Pikud Haoref alert."""

    # Stable identity
    alert_id: str  # original id or computed hash

    # Payload fields (best-effort)
    title: str = ""
    cities: list[str] = field(default_factory=list)
    areas: list[str] = field(default_factory=list)
    region: str = ""
    description: str = ""
    category: str = ""
    threat: str = ""
    event_time: str = ""  # raw string as received

    # Drill flag – set when we can detect it
    is_drill: bool = False

    # Shelter instructions (Hebrew)
    instructions: str = ""

    # Preserved for debugging
    raw: dict[str, Any] = field(default_factory=dict)


# Keys that are stable enough to form a hash identity
_HASH_KEYS = ("title", "cities", "areas", "region", "category", "threat")

# Maps the string `type` field from pikud-haoref-api → numeric category string
# used by _CATEGORY in slack_notifier.py
_TYPE_TO_CATEGORY: dict[str, str] = {
    "missiles":                      "1",
    # "general" intentionally omitted — its title IS the meaningful label
    # (e.g. "האירוע הסתיים", "בדקות הקרובות צפויות להתקבל התרעות באזורך")
    "hostileAircraftIntrusion":       "5",
    "hazardousMaterials":             "7",
    "earthQuake":                    "20",
    "tsunami":                       "14",
    "terroristInfiltration":         "15",
    # "newsFlash" intentionally omitted — use its title as the Slack header
    # drill variants map to the same categories
    "missilesDrill":                 "1",
    "hostileAircraftIntrusionDrill": "5",
    "hazardousMaterialsDrill":       "7",
    "earthQuakeDrill":               "20",
    "tsunamiDrill":                  "14",
    "terroristInfiltrationDrill":    "15",
    "radiologicalEvent":             "7",
    "radiologicalEventDrill":        "7",
}


def _stable_hash(data: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 hex digest over important fields."""
    parts: list[str] = []
    for key in _HASH_KEYS:
        val = data.get(key, "")
        if isinstance(val, list):
            parts.append(key + "=" + ",".join(sorted(str(v) for v in val)))
        else:
            parts.append(key + "=" + str(val))
    # Also include a normalised form of the full raw payload as a tiebreaker
    parts.append("raw=" + json.dumps(data, sort_keys=True, ensure_ascii=False))
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:24]


def _is_drill(data: dict[str, Any]) -> bool:
    lower_str = json.dumps(data, ensure_ascii=False).lower()
    drill_keywords = ("drill", "test", "תרגיל", "בדיקה")
    return any(kw in lower_str for kw in drill_keywords)


def parse_alert(raw_data: str) -> Alert | None:
    """
    Parse raw SSE data string into an Alert.
    Returns None on any parse failure so the caller can safely skip it.
    """
    try:
        data = json.loads(raw_data)
    except json.JSONDecodeError as exc:
        log.warning("Failed to decode alert JSON: %s | raw=%r", exc, raw_data[:200])
        return None

    if not isinstance(data, dict):
        log.warning("Alert payload is not a JSON object: %r", raw_data[:200])
        return None

    # Normalise common field name variants -----------------------------------

    def _get(*keys: str, default: Any = "") -> Any:
        for k in keys:
            if k in data:
                return data[k]
        return default

    alert_id: str = str(data["id"]) if "id" in data else _stable_hash(data)

    cities_raw = _get("cities", "אזורים", default=[])
    if isinstance(cities_raw, str):
        cities_raw = [cities_raw]

    areas_raw = _get("areas", "areas_to_protect", default=[])
    if isinstance(areas_raw, str):
        areas_raw = [areas_raw]

    # Resolve category: prefer numeric `category`/`cat`, fall back to `type` string
    category_raw = str(_get("category", "קטגוריה", "cat", default=""))
    if not category_raw or category_raw in ("קטגוריה", "cat"):
        type_str = str(data.get("type", ""))
        category_raw = _TYPE_TO_CATEGORY.get(type_str, "")

    # Resolve title: prefer explicit `title`, fall back to `instructions` (used by pikud-haoref-api)
    title_raw = str(_get("title", "כותרת", default=""))
    if not title_raw or title_raw == "כותרת":
        title_raw = str(_get("instructions", "הנחיות", default=""))

    return Alert(
        alert_id=alert_id,
        title=title_raw,
        cities=list(cities_raw),
        areas=list(areas_raw),
        region=str(_get("region", "מחוז", "district")),
        description=str(_get("description", "תיאור")),
        category=category_raw,
        threat=str(_get("threat", "איום")),
        event_time=str(_get("event_time", "time", "timestamp")) or str(datetime.now().timestamp()),
        instructions=str(_get("instructions", "הנחיות")),
        is_drill=_is_drill(data),
        raw=data,
    )
