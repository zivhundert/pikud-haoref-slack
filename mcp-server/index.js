/**
 * Pikud Ha'oref MCP Server + SSE Bridge
 *
 * This file is part of the pikud-haoref-daemon project.
 * The Pikud Ha'oref API integration is powered by Leon Melamud's MCP:
 *   https://github.com/LeonMelamud/pikud-a-oref-mcp
 *
 * What runs here:
 *
 * 1. SSE bridge — port 8000 — /api/webhook/alerts  /api/alerts-stream
 *    Polls oref.org.il every 3 s via pikud-haoref-api (Leon's package) and
 *    re-emits `event: new_alert` frames to any connected SSE client.
 *    The Python daemon subscribes here.
 *
 * 2. MCP HTTP server — port 8001 — /mcp
 *    StreamableHTTP JSON-RPC endpoint for VS Code Copilot Chat.
 *
 * MCP tools:
 *   get_active_alert   – direct live query of the Pikud Ha'oref API
 *   get_recent_alerts  – last N alerts from the daemon's SQLite DB
 *   get_daemon_status  – data/status.json written by the Python daemon
 *   get_sample_alert   – realistic example alert payload
 *
 * Credits:
 *   Leon Melamud — https://github.com/LeonMelamud/pikud-a-oref-mcp
 *   Pikud Ha'oref — https://www.oref.org.il
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { createRequire } from "module";
import { promises as fs } from "fs";
import http from "http";
import { randomUUID } from "crypto";
import path from "path";
import { fileURLToPath } from "url";

// pikud-haoref-api is CommonJS
const require = createRequire(import.meta.url);
const pikudHaoref = require("pikud-haoref-api");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Paths are relative to the project root (one level up from mcp-server/)
const PROJECT_ROOT = path.resolve(__dirname, "..");
const STATUS_FILE = path.join(PROJECT_ROOT, "data", "status.json");
const DB_FILE = path.join(PROJECT_ROOT, "data", "alerts.db");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Promisify pikud-haoref-api's callback-based getActiveAlert */
function getActiveAlertAsync(options = {}) {
  return new Promise((resolve, reject) => {
    pikudHaoref.getActiveAlert((err, alert) => {
      if (err) reject(err);
      else resolve(alert);
    }, options);
  });
}

async function readStatusFile() {
  try {
    const raw = await fs.readFile(STATUS_FILE, "utf8");
    return JSON.parse(raw);
  } catch {
    return { error: "Status file not found – is the daemon running?" };
  }
}

async function readRecentAlerts(limit = 10) {
  // Use dynamic import so the sqlite3 native module is optional
  try {
    // Use the built-in child_process to run a quick sqlite3 query
    const { execFile } = await import("child_process");
    const { promisify } = await import("util");
    const execAsync = promisify(execFile);
    const query = `
      SELECT alert_id, title, cities, region, event_time, received_at, endpoint, slack_result
      FROM alert_log
      ORDER BY received_at DESC
      LIMIT ${Number(limit)};
    `;
    const { stdout } = await execAsync("sqlite3", [
      "-json",
      DB_FILE,
      query,
    ]);
    let rows = [];
    try {
      rows = JSON.parse(stdout.trim() || "[]");
    } catch {
      rows = [];
    }
    // Parse JSON city arrays stored as strings
    return rows.map((r) => {
      try {
        r.cities = JSON.parse(r.cities || "[]");
      } catch {
        r.cities = [];
      }
      return r;
    });
  } catch (err) {
    return { error: `Could not read alert DB: ${err.message}` };
  }
}

// ---------------------------------------------------------------------------
// MCP Tool registration
// ---------------------------------------------------------------------------

function registerTools(s) {
// ── Tool: get_active_alert ──────────────────────────────────────────────────
s.tool(
  "get_active_alert",
  "Query the live Pikud Ha'oref API for the currently active alert. " +
    "Note: the API is only accessible from within Israel or via an Israeli proxy.",
  {}, // no input parameters needed
  async () => {
    try {
      const alert = await getActiveAlertAsync();
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(alert, null, 2),
          },
        ],
      };
    } catch (err) {
      return {
        content: [
          {
            type: "text",
            text: `Error querying Pikud Ha'oref API: ${err.message}\n\n` +
              "This API is geo-restricted to Israeli IPs. " +
              "If you are outside Israel, set an Israeli proxy via the PIKUD_PROXY env var.",
          },
        ],
        isError: true,
      };
    }
  }
);

// ── Tool: get_recent_alerts ─────────────────────────────────────────────────
s.tool(
  "get_recent_alerts",
  "Read the last N alerts recorded by the running daemon from the local SQLite database.",
  {
    limit: {
      type: "number",
      description: "How many recent alerts to return (default 10, max 50)",
    },
  },
  async ({ limit = 10 }) => {
    const alerts = await readRecentAlerts(Math.min(Number(limit), 50));
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(alerts, null, 2),
        },
      ],
    };
  }
);

// ── Tool: get_daemon_status ─────────────────────────────────────────────────
s.tool(
  "get_daemon_status",
  "Read the current operational status of the Pikud Ha'oref daemon " +
    "(connectivity, last alert, Slack result, reconnect count, etc.).",
  {},
  async () => {
    const status = await readStatusFile();
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(status, null, 2),
        },
      ],
    };
  }
);

// ── Tool: get_sample_alert ──────────────────────────────────────────────────
s.tool(
  "get_sample_alert",
  "Return a realistic example Pikud Ha'oref alert payload showing all fields " +
    "the daemon can receive. Useful for tests and understanding the data model.",
  {},
  async () => {
    const sample = {
      id: "134168709720000000",
      type: "missiles",
      title: "ירי רקטות וטילים",
      cities: ["תל אביב - מזרח", "חיפה - כרמל ועיר תחתית", "עין גדי"],
      areas: ["מרכז", "צפון", "דרום"],
      region: "מרכז",
      description: "אזור הספר עוטף עזה",
      instructions: "היכנסו למבנה, נעלו את הדלתות וסגרו את החלונות",
      category: "מטח",
      threat: "ירי רקטות",
      event_time: String(Math.floor(Date.now() / 1000)),
    };
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(sample, null, 2),
        },
      ],
    };
  }
);
} // end registerTools

// ---------------------------------------------------------------------------
// Start — StreamableHTTP MCP server on :8001
// ---------------------------------------------------------------------------

// Stateful mode: each client gets a session ID so VS Code Copilot can
// correlate initialize ↔ tool-call requests correctly.
// A new transport is created per session; sessions are stored in this map.
const sessions = new Map(); // sessionId → transport

const MCP_PORT = 8001;
const mcpHttpServer = http.createServer(async (req, res) => {
  // CORS so VS Code can connect from any origin
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
  res.setHeader(
    "Access-Control-Allow-Headers",
    "Content-Type, Accept, Mcp-Session-Id"
  );

  if (req.method === "OPTIONS") {
    res.writeHead(204).end();
    return;
  }

  if (req.url === "/mcp" || req.url.startsWith("/mcp?")) {
    // Read body first (SDK needs the parsed body on POST)
    let rawBody = "";
    await new Promise((resolve) => {
      req.on("data", (chunk) => (rawBody += chunk));
      req.on("end", resolve);
    });

    let parsedBody;
    if (rawBody) {
      try { parsedBody = JSON.parse(rawBody); } catch { /* ignore */ }
    }

    const sessionId = req.headers["mcp-session-id"];

    // Route to existing session
    if (sessionId && sessions.has(sessionId)) {
      await sessions.get(sessionId).handleRequest(req, res, parsedBody);
      return;
    }

    // New session: only allow if this is an initialize request
    const isInit =
      parsedBody?.method === "initialize" ||
      (Array.isArray(parsedBody) && parsedBody.some((r) => r.method === "initialize"));

    if (!sessionId && !isInit) {
      res.writeHead(400, { "Content-Type": "text/plain" });
      res.end("Bad Request: missing Mcp-Session-Id");
      return;
    }

    // Create a fresh transport + server clone for this session
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: () => randomUUID(),
    });

    // Clean up session when transport closes
    transport.onclose = () => {
      if (transport.sessionId) sessions.delete(transport.sessionId);
    };

    // Wire a fresh server instance to this transport
    const sessionServer = new McpServer({ name: "pikud-haoref", version: "0.1.0" });

    // Re-register all tools on the session server
    registerTools(sessionServer);

    await sessionServer.connect(transport);

    // Store session after connect (sessionId is set during initialize handling)
    await transport.handleRequest(req, res, parsedBody);

    if (transport.sessionId) {
      sessions.set(transport.sessionId, transport);
    }
  } else {
    res.writeHead(404).end("Not found");
  }
});

mcpHttpServer.listen(MCP_PORT, () => {
  process.stderr.write(
    `Pikud Ha'oref MCP server ready → http://localhost:${MCP_PORT}/mcp\n`
  );
});

// ---------------------------------------------------------------------------
// SSE Bridge — forward live oref.org.il alerts to the Python daemon on :8000
// ---------------------------------------------------------------------------

/** All currently connected SSE response streams (Python daemon connections). */
const sseClients = new Set();

/** Recently broadcast alert IDs → timestamp (ms). Prevents re-broadcasting within TTL. */
const recentBroadcastIds = new Map();
const RECENT_ID_TTL_MS = 90_000; // 90 s

function alreadyBroadcast(id) {
  const strId = String(id);
  const ts = recentBroadcastIds.get(strId);
  if (!ts) return false;
  if (Date.now() - ts > RECENT_ID_TTL_MS) {
    recentBroadcastIds.delete(strId);
    return false;
  }
  return true;
}

/** Guard against overlapping poll calls (e.g. slow network round-trip). */
let _polling = false;

/** Poll the real Pikud Ha'oref API and broadcast any new alert to all clients. */
async function pollAndBroadcast() {
  if (_polling) return;
  _polling = true;
  try {
    const alert = await getActiveAlertAsync();
    if (
      alert &&
      alert.type !== "none" &&
      alert.id != null &&
      !alreadyBroadcast(alert.id)
    ) {
      recentBroadcastIds.set(String(alert.id), Date.now());
      const payload = JSON.stringify(alert);
      process.stderr.write(
        `SSE: broadcasting new_alert id=${alert.id} type=${alert.type}\n`
      );
      for (const res of sseClients) {
        try {
          res.write(`event: new_alert\ndata: ${payload}\n\n`);
        } catch {
          // Client disconnected mid-write; the close handler cleans up
        }
      }
    }
  } catch (err) {
    process.stderr.write(`SSE poll error: ${err.message}\n`);
  } finally {
    _polling = false;
  }
}

// Start polling immediately, then every 3 seconds
pollAndBroadcast();
setInterval(pollAndBroadcast, 3000);

const SSE_PORT = 8000;
const sseServer = http.createServer((req, res) => {
  // POST /api/inject — broadcast a fake alert as an SSE event.
  // The posted JSON flows through the daemon's full pipeline (parse → dedupe → Slack → log)
  // instead of being written directly to SQLite.
  if (req.method === "POST" && req.url === "/api/inject") {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      let alert;
      try {
        alert = JSON.parse(body);
      } catch {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "Invalid JSON" }));
        return;
      }
      // Ensure required fields
      if (!alert.id) alert.id = String(Date.now());
      if (!alert.type) alert.type = "general";
      if (!Array.isArray(alert.cities)) alert.cities = [];
      const payload = JSON.stringify(alert);
      for (const client of sseClients) {
        try {
          client.write(`event: new_alert\ndata: ${payload}\n\n`);
        } catch { /* disconnected */ }
      }
      process.stderr.write(
        `SSE: injected alert id=${alert.id} type=${alert.type} to ${sseClients.size} client(s)\n`
      );
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, clients: sseClients.size }));
    });
    return;
  }

  if (
    req.url === "/api/webhook/alerts" ||
    req.url === "/api/alerts-stream"
  ) {
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.writeHead(200);

    // Initial keepalive so the client knows the stream is live
    res.write(": connected\n\n");

    sseClients.add(res);
    process.stderr.write(
      `SSE: client connected (total: ${sseClients.size})\n`
    );

    // Send a keepalive comment every 15 s to prevent proxy timeouts
    const keepalive = setInterval(() => {
      try {
        res.write(": keepalive\n\n");
      } catch {
        clearInterval(keepalive);
      }
    }, 15_000);

    req.on("close", () => {
      sseClients.delete(res);
      clearInterval(keepalive);
      process.stderr.write(
        `SSE: client disconnected (total: ${sseClients.size})\n`
      );
    });
  } else {
    res.writeHead(404).end("Not found");
  }
});

sseServer.listen(SSE_PORT, () => {
  process.stderr.write(
    `SSE bridge ready → http://localhost:${SSE_PORT}/api/webhook/alerts\n`
  );
});
