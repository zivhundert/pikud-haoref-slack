# Architecture

> The alert feed is powered by [Leon Melamud's `pikud-a-oref-mcp`](https://github.com/LeonMelamud/pikud-a-oref-mcp).
> This project wraps it with a local SSE bridge, a Python Slack-forwarding daemon, and a web dashboard.

```mermaid
flowchart TD
    subgraph external["External"]
        OREF["oref.org.il\nAlert API"]
        SLACK["Slack\nIncoming Webhook"]
    end

    subgraph node["Node.js Process (mcp-server/index.js)"]
        POLL["pikud-haoref-api\npolls every 3 s"]
        SSE_BRIDGE["SSE Bridge\nlocalhost:8000\n/api/webhook/alerts\n/api/alerts-stream"]
        MCP_HTTP["MCP HTTP Server\nlocalhost:8001/mcp"]
    end

    subgraph python["Python Daemon (app/)"]
        SSE_LISTENER["SSEListener\nsse_listener.py"]
        PARSER["AlertParser\nalert_parser.py"]
        DEDUPE["DedupeStore\nSQLite · dedupe_store.py"]
        NOTIFIER["SlackNotifier\nslack_notifier.py"]
        STATUS["StatusStore\nstatus_store.py"]
        ALERT_LOG["AlertLog\nalert_log.py"]
        WEB["Web Dashboard\naiohttp · localhost:8080"]
    end

    subgraph storage["Local Storage (data/)"]
        DB[("alerts.db\nSQLite")]
        STATUSJSON["status.json"]
    end

    subgraph vscode["VS Code / Copilot Chat"]
        COPILOT["GitHub Copilot Chat\nMCP Client"]
    end

    OREF -->|"HTTP JSON poll"| POLL
    POLL -->|"new_alert SSE event"| SSE_BRIDGE
    SSE_BRIDGE -->|"text/event-stream"| SSE_LISTENER

    SSE_LISTENER --> PARSER
    PARSER --> DEDUPE
    DEDUPE -->|"not duplicate"| NOTIFIER
    DEDUPE -->|"write"| DB
    NOTIFIER -->|"Block Kit POST"| SLACK
    NOTIFIER --> ALERT_LOG
    ALERT_LOG -->|"INSERT"| DB
    SSE_LISTENER --> STATUS
    STATUS -->|"write"| STATUSJSON

    DB -->|"SELECT"| WEB
    STATUSJSON -->|"read"| WEB

    DB -->|"SELECT"| MCP_HTTP
    STATUSJSON -->|"read"| MCP_HTTP
    OREF -.->|"direct poll\n(get_active_alert tool)"| MCP_HTTP
    MCP_HTTP <-->|"StreamableHTTP\nJSON-RPC"| COPILOT
```
