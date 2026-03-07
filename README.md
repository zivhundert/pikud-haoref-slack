# oref-slack

> A local server wrapper that fetches real-time Pikud Ha'oref (Israel Home Front Command) alerts and forwards them instantly to your Slack channel.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/node-%3E%3D18-green.svg)](https://nodejs.org/)

---

## Built on Leon Melamud's Pikud Ha'oref MCP

This project is a **wrapper and local runtime** around
[**Leon Melamud's `pikud-a-oref-mcp`**](https://github.com/LeonMelamud/pikud-a-oref-mcp).

Leon's MCP server provides the core integration with the official Pikud Ha'oref
API — this repo adds:

- A **local SSE bridge** (Node.js, port 8000) that re-streams Leon's alert feed
  so multiple local consumers can subscribe
- A **Python daemon** that consumes the SSE stream, deduplicates alerts, and
  pushes rich Slack Block Kit messages to your organisation's channel
- A **web dashboard** (port 8080) to monitor connectivity and alert history
- A **GitHub Copilot / MCP HTTP endpoint** (port 8001) for developer tooling

> **Full credit** for the Pikud Ha'oref API integration goes to
> [@LeonMelamud](https://github.com/LeonMelamud). Please ⭐ his repo!

---

## How it works

```
oref.org.il ──► Node SSE bridge (port 8000)
                     │
                     ▼
              Python SSE daemon
              ├── deduplication (SQLite)
              ├── city / region filters
              ├── Slack Block Kit message
              └── web dashboard (port 8080)

VS Code Copilot Chat ◄──► MCP HTTP server (port 8001)
```

1. The Node.js process polls the live Pikud Ha'oref API via `pikud-haoref-api`
   (Leon's package) every 3 seconds and re-emits `event: new_alert` frames over SSE.
2. The Python daemon maintains a persistent SSE connection, parses every
   `new_alert` event into a typed object, and deduplicates by alert ID.
3. Each new, non-duplicate alert that passes your city/region filters is sent to
   Slack as a rich Block Kit message.
4. A local web dashboard and GitHub Copilot MCP tools let you inspect daemon
   state, recent alerts, and the live Pikud Ha'oref feed during development.

---

## Prerequisites

| Tool | Version |
|---|---|
| Python | 3.12+ |
| Node.js | 18+ |
| npm | 9+ |

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/oref-slack.git
cd oref-slack

# 2. Python environment
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Node dependencies (SSE bridge + MCP server)
cd mcp-server && npm install && cd ..

# 4. Configure
cp .env.example .env
# Edit .env — add your SLACK_WEBHOOK_URL

# 5a. Start the SSE bridge + MCP server (Node)
node mcp-server/index.js &

# 5b. Start the Python daemon
python -m app.main run
```

Open **http://localhost:8080** for the dashboard.

---

## Environment variables

### Required

| Variable | Description |
|---|---|
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL for your channel |

### Optional

| Variable | Default | Description |
|---|---|---|
| `PIKUD_SSE_URL` | `http://localhost:8000/api/webhook/alerts` | Primary SSE endpoint (the local bridge) |
| `PIKUD_SSE_FALLBACK_URL` | `http://localhost:8000/api/alerts-stream` | Fallback SSE endpoint |
| `PIKUD_API_KEY` | _(empty)_ | Optional `X-API-Key` header for the upstream service |
| `CITY_FILTERS` | _(empty)_ | Comma-separated Hebrew city names to filter by |
| `REGION_FILTERS` | _(empty)_ | Comma-separated region names to filter by |
| `INCLUDE_DRILLS` | `false` | Set `true` to also forward drill/test alerts |
| `DEDUPE_TTL_SECONDS` | `900` | Seconds to remember a seen alert ID |
| `DB_PATH` | `data/alerts.db` | SQLite database path |
| `STATUS_FILE_PATH` | `data/status.json` | Status file path |
| `LOG_LEVEL` | `INFO` | Python log level |
| `TIMEZONE` | `Asia/Jerusalem` | Timezone for Slack timestamps |
| `WEB_HOST` | `0.0.0.0` | Host to bind the web dashboard to |

---

## Running with Docker

```bash
# Build
docker build -t oref-slack .

# Run
docker run --rm \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  oref-slack
```

The container healthcheck reads `data/status.json` and verifies `ready=true`
and a recent keepalive timestamp.

---

## CLI commands

```bash
python -m app.main run          # Start the daemon
python -m app.main status       # Print status JSON
python -m app.main print-last   # Pretty-print last alert
python -m app.main test-slack   # Send a test Slack message
```

---

## GitHub Copilot / MCP tools

The Node process also exposes an MCP HTTP server at `http://localhost:8001/mcp`
for use with VS Code Copilot Chat. The `.vscode/mcp.json` configures it
automatically. Available tools:

| Tool | Description |
|---|---|
| `get_active_alert` | Query the live Pikud Ha'oref API directly |
| `get_recent_alerts` | Read recent alerts from the local SQLite DB |
| `get_daemon_status` | Read `data/status.json` |
| `get_sample_alert` | Return an example alert payload (illustrative — not all fields come from the live API) |

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for a Mermaid diagram.

---

## Credits

- **[Leon Melamud](https://github.com/LeonMelamud)** — author of
  [`pikud-a-oref-mcp`](https://github.com/LeonMelamud/pikud-a-oref-mcp), the
  MCP server and `pikud-haoref-api` integration that powers the alert feed in
  this project.
- **[Pikud Ha'oref](https://www.oref.org.il/)** — Israel Home Front Command,
  the source of all alert data.

---

## Contributing

Pull requests are welcome. Please open an issue first to discuss significant
changes. Make sure `pytest` passes before submitting.

```bash
pip install -e ".[dev]"
pytest
```

---

## License

MIT — see [LICENSE](LICENSE).

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
# Simulate an SSE event through the Node bridge's inject endpoint
curl -X POST http://localhost:8000/api/inject \
  -H "Content-Type: application/json" \
  -d '{"id":"test-1","type":"missiles","cities":["חיפה"],"instructions":"היכנסו למרחב מוגן"}'
```

4. Watch daemon logs and check Slack.

---

## Inspecting the live SSE stream with curl

```bash
curl -N http://localhost:8000/api/webhook/alerts
```

You will see keep-alive lines (`: keepalive`) and event blocks like:

```
event: new_alert
data: {"type":"missiles","cities":["תל אביב - מזרח"],"instructions":"היכנסו למרחב מוגן","id":"134168709720000000"}

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
