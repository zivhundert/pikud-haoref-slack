"""
Inject fake alerts for demo / smoke-testing purposes.

Alerts are posted to the Node SSE bridge (POST /api/inject) so they flow
through the daemon's full pipeline:  parse → dedupe → Slack → DB log.
Nothing is written directly to SQLite.
"""
import json
import time
import urllib.request

SSE_INJECT = "http://localhost:8000/api/inject"
DASHBOARD_ALERTS = "http://localhost:8080/api/alerts"

# Real pikud-haoref-api shaped payloads
fake_alerts = [
    {
        "id": f"inject-{int(time.time())}-001",
        "type": "missiles",
        "cities": ["תל אביב - מזרח", "רמת גן"],
        "instructions": "היכנסו למרחב מוגן מיד",
    },
    {
        "id": f"inject-{int(time.time())}-002",
        "type": "hostileAircraftIntrusion",
        "cities": ["חיפה", "קריית אתא"],
        "instructions": "היכנסו למבנה מוגן",
    },
    {
        "id": f"inject-{int(time.time())}-003",
        "type": "terroristInfiltration",
        "cities": ["נתיבות"],
        "instructions": "נעלו דלתות וחלונות",
    },
]

injected = 0
for alert in fake_alerts:
    body = json.dumps(alert, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        SSE_INJECT,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
            print(f"  injected {alert['type']} → {result}")
            injected += 1
    except Exception as exc:
        print(f"  failed to inject {alert['type']}: {exc}")
    time.sleep(0.3)   # small gap so dedupe IDs stay distinct

print(f"\nInjected {injected}/{len(fake_alerts)} alerts via SSE bridge")

# Give the daemon a moment to process, then show the dashboard
time.sleep(1.5)
try:
    resp = urllib.request.urlopen(DASHBOARD_ALERTS, timeout=5)
    data = json.loads(resp.read())
    print(f"Dashboard now has {len(data)} alerts:")
    for entry in data[:10]:
        cities = ", ".join(entry.get("cities") or [])
        print(f"  [{entry['slack_result']:9s}] {entry['title'] or '(no title)'}  →  {cities}")
except Exception as exc:
    print(f"Could not reach dashboard: {exc}")
