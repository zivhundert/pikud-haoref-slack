# Pikud Haoref → Slack Daemon

A minimal, single-process Python 3.12 daemon that listens to Pikud Haoref
(Israel Home Front Command) real-time alerts via Server-Sent Events (SSE) and
forwards each new, deduplicated alert to a Slack incoming webhook.

## What it does

1. Opens a persistent SSE connection to the upstream alert service.
2. Parses each `event: new_alert` frame into a typed Python object.
3. Deduplicates alerts using a local SQLite store (no Redis required).
4. Optionally filters by city or region and suppresses drill alerts.
5. Sends a rich Block Kit message to your Slack channel.
6. Reconnects automatically with exponential back-off if the stream drops.
7. Writes a local `data/status.json` file you can inspect at any time.

---

## Required environment variables

| Variable | Description |
|---|---|
| `SLACK_WEBHOOK_URL` | Your Slack incoming webhook URL |
| `PIKUD_API_KEY` | `X-API-Key` header value for the upstream service |

## Optional environment variables

| Variable | Default | Description |
|---|---|---|
| `PIKUD_SSE_URL` | `http://localhost:8000/api/webhook/alerts` | Primary SSE endpoint |
| `PIKUD_SSE_FALLBACK_URL` | `http://localhost:8000/api/alerts-stream` | Fallback SSE endpoint |
| `CITY_FILTERS` | _(empty)_ | Comma-separated Hebrew city names |
| `REGION_FILTERS` | _(empty)_ | Comma-separated region names |
| `INCLUDE_DRILLS` | `false` | Set `true` to forward drill alerts |
| `DEDUPE_TTL_SECONDS` | `900` | How long to remember a seen alert |
| `DB_PATH` | `data/alerts.db` | SQLite database path |
| `STATUS_FILE_PATH` | `data/status.json` | Status file path |
| `LOG_LEVEL` | `INFO` | Python log level |
| `TIMEZONE` | `Asia/Jerusalem` | Timezone for Slack timestamps |

---

## Running locally

```bash
# 1. Clone / open the project
cd pikud-haoref-daemon

# 2. Create a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Configure
cp .env.example .env
# Edit .env – fill in SLACK_WEBHOOK_URL and PIKUD_API_KEY

# 5. Start the daemon
python -m app.main run
```

---

## Running with Docker

```bash
# Build
docker build -t pikud-daemon .

# Run (pass env vars from .env file)
docker run --rm \
  --env-file .env \
  -v "$(pwd)/data:/daemon/data" \
  pikud-daemon
```

The container healthcheck reads `data/status.json` and verifies `ready=true`
and a recent keepalive timestamp.

---

## CLI commands

```bash
# Start the long-running daemon
python -m app.main run

# Print the current status JSON
python -m app.main status

# Print the last alert summary  
python -m app.main print-last

# Send a test message to Slack
python -m app.main test-slack
```

---

## Inspecting status

```bash
# Via CLI
python -m app.main status

# Directly
cat data/status.json
```

Example output:

```json
{
  "started_at": "2024-11-14T10:00:00Z",
  "ready": true,
  "connected": true,
  "current_endpoint": "http://localhost:8000/api/webhook/alerts",
  "last_keepalive_at": "2024-11-14T10:05:30Z",
  "last_alert_at": "2024-11-14T09:55:00Z",
  "last_alert_summary": "ירי רקטות | תל אביב, יפו",
  "last_slack_result": "ok",
  "last_error": null,
  "reconnect_count": 1
}
```

---

## Sending a test Slack message

```bash
python -m app.main test-slack
```

This sends a clearly-marked `[TEST]` message — not a real alert.

---

## Testing end-to-end against the upstream project

1. Start the upstream MCP / webhook server on port 8000.
2. Start the daemon: `python -m app.main run`
3. Inject a fake alert via curl:

```bash
# Simulate an SSE event against your local upstream
curl -X POST http://localhost:8000/api/inject-alert \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"id":"test-1","title":"ירי רקטות","cities":["חיפה"],"region":"צפון"}'
```

4. Watch daemon logs and check Slack.

---

## Inspecting the live SSE stream with curl

```bash
curl -N \
  -H "Accept: text/event-stream" \
  -H "X-API-Key: your-api-key" \
  http://localhost:8000/api/webhook/alerts
```

You will see keep-alive lines (`: keep-alive`) and event blocks like:

```
event: new_alert
data: {"id":"abc","title":"ירי רקטות","cities":["תל אביב"]}

```

---

## Using `.vscode/mcp.json` with GitHub Copilot Chat

The `.vscode/mcp.json` file registers the upstream MCP server with GitHub
Copilot Chat so you can inspect sample alerts and connection status from the
chat panel **during development only**.

1. Start the upstream MCP server on port 8001.
2. Open VS Code in this directory.
3. Ask Copilot Chat: _"What does a sample alert look like?"_ or
   _"What is the current connection status?"_

> **Important:** The running daemon connects directly to the SSE stream and
> does NOT use MCP tool calls at runtime. MCP is for development inspection
> only.

---

## Running tests

```bash
pytest -v
```

---

## Linting

```bash
ruff check .
```

---

## Troubleshooting

### API key mismatch

- Check `PIKUD_API_KEY` in `.env` matches what the upstream expects.
- The upstream will typically return `401` or close the SSE stream immediately.
- Watch for `HTTP error on ...: 401` in daemon logs.

### SSE disconnects

- Normal. The daemon reconnects automatically with exponential back-off.
- Check `reconnect_count` in `data/status.json`.
- If reconnects happen constantly, verify the endpoint URL and API key.

### Duplicate alerts

- Duplicates are suppressed for `DEDUPE_TTL_SECONDS` (default 15 minutes).
- If you see the same alert appear multiple times in Slack, lower the TTL or
  check whether the upstream is sending the same `id` for distinct events.

### Slack failures

- Verify `SLACK_WEBHOOK_URL` is valid with `python -m app.main test-slack`.
- Common causes: webhook URL revoked, Slack app removed, network proxy.

### Hebrew encoding

- Make sure your terminal / Docker base image uses UTF-8.
- The daemon uses `ensure_ascii=False` throughout for Hebrew preservation.
- If Slack shows garbled text, check whether a proxy is re-encoding the body.

### Upstream not reachable

- Confirm the upstream is running and accessible:
  ```bash
  curl -I http://localhost:8000/api/webhook/alerts
  ```
- Check firewall rules and that you're on the correct network.

### Running outside Israel or without an Israeli IP

- Some upstream deployments are geo-restricted.
- Use a VPN with an Israeli exit node or deploy the daemon inside Israel.
- Alternatively, run the upstream proxy on a machine with Israeli access and
  expose it to your daemon via a tunnel.
