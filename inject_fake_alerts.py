"""Inject fake alerts for demo purposes."""
import json
import sqlite3
import time
import urllib.request

DB = "data/alerts.db"

conn = sqlite3.connect(DB)
conn.execute("""
CREATE TABLE IF NOT EXISTS alert_log (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT, title TEXT, cities TEXT, region TEXT,
    description TEXT, event_time TEXT, received_at REAL,
    endpoint TEXT, slack_result TEXT, raw TEXT
)""")

fake = [
    {
        "alert_id": "sim-001",
        "title": "ירי רקטות",
        "cities": json.dumps(["תל אביב", "רמת גן"], ensure_ascii=False),
        "region": "מרכז",
        "description": "כוחות בכוננות",
        "event_time": "1741267200",
        "received_at": time.time() - 30,
        "endpoint": "http://localhost:8000/api/webhook/alerts",
        "slack_result": "ok",
        "raw": "{}",
    },
    {
        "alert_id": "sim-002",
        "title": "חדירת כטב״ם",
        "cities": json.dumps(["חיפה", "קריית אתא"], ensure_ascii=False),
        "region": "צפון",
        "description": "",
        "event_time": "1741267260",
        "received_at": time.time() - 10,
        "endpoint": "http://localhost:8000/api/alerts-stream",
        "slack_result": "ok",
        "raw": "{}",
    },
    {
        "alert_id": "sim-003",
        "title": "ירי רקטות",
        "cities": json.dumps(["באר שבע"], ensure_ascii=False),
        "region": "דרום",
        "description": "",
        "event_time": "1741267290",
        "received_at": time.time() - 3,
        "endpoint": "http://localhost:8000/api/webhook/alerts",
        "slack_result": "error",
        "raw": "{}",
    },
]

for a in fake:
    conn.execute(
        """
        INSERT OR IGNORE INTO alert_log
          (alert_id,title,cities,region,description,event_time,received_at,endpoint,slack_result,raw)
        VALUES (:alert_id,:title,:cities,:region,:description,:event_time,:received_at,:endpoint,:slack_result,:raw)
        """,
        a,
    )

conn.commit()
conn.close()
print(f"Injected {len(fake)} fake alerts")

resp = urllib.request.urlopen("http://localhost:8080/api/alerts")
data = json.loads(resp.read())
print(f"Dashboard API returns {len(data)} alerts:")
for entry in data:
    cities = ", ".join(entry.get("cities") or [])
    print(f"  [{entry['slack_result']:8s}] {entry['title']}  →  {cities}")
