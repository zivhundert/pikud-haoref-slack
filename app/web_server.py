"""
Lightweight aiohttp dashboard.

Routes:
  GET /           → HTML dashboard (all JS/CSS inline, no CDN)
  GET /api/status → current status JSON
  GET /api/config → config JSON (sensitive values masked)
  GET /api/alerts → recent alert log JSON
  GET /events     → browser-facing SSE stream (status + alert pushes)
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Browser-facing SSE broadcaster
# ---------------------------------------------------------------------------


class Broadcaster:
    """Push named SSE events to all connected browser clients."""

    def __init__(self) -> None:
        self._clients: list[asyncio.Queue[str]] = []

    def add_client(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
        self._clients.append(q)
        log.debug("Browser SSE client connected (total %d)", len(self._clients))
        return q

    def remove_client(self, q: asyncio.Queue[str]) -> None:
        try:
            self._clients.remove(q)
        except ValueError:
            pass
        log.debug("Browser SSE client disconnected (total %d)", len(self._clients))

    def push(self, event: str, data: Any) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        dead: list[asyncio.Queue[str]] = []
        for q in list(self._clients):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.remove_client(q)


# ---------------------------------------------------------------------------
# In-memory connection log
# ---------------------------------------------------------------------------


class ConnectionLogger:
    """Keeps the last MAX_ENTRIES log lines from the SSE listener in memory."""

    MAX_ENTRIES = 200

    def __init__(self) -> None:
        self._entries: deque[dict[str, str]] = deque(maxlen=self.MAX_ENTRIES)

    def append(self, level: str, msg: str) -> None:
        self._entries.appendleft(
            {
                "ts_iso": datetime.now(UTC).strftime("%H:%M:%S"),
                "level": level,
                "msg": msg,
            }
        )

    def recent(self, limit: int = 100) -> list[dict[str, str]]:
        return list(self._entries)[:limit]


# ---------------------------------------------------------------------------
# HTML dashboard (single self-contained page)
# ---------------------------------------------------------------------------

_HTML = """\
<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Pikud Haoref → Slack</title>
<style>
  :root {
    --bg: #0f1117;
    --card: #1a1d27;
    --border: #2a2d3a;
    --text: #e2e8f0;
    --muted: #64748b;
    --green: #22c55e;
    --red: #ef4444;
    --yellow: #f59e0b;
    --blue: #3b82f6;
    --accent: #6366f1;
    --font: 'Segoe UI', system-ui, -apple-system, sans-serif;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--font);
         min-height: 100vh; padding: 24px 20px 60px; }
  a { color: var(--blue); }

  /* Header */
  .header { display: flex; align-items: center; gap: 12px; margin-bottom: 28px; }
  .header h1 { font-size: 1.4rem; font-weight: 700; letter-spacing: -.3px; }
  .status-dot { width: 13px; height: 13px; border-radius: 50%;
                background: var(--muted); flex-shrink: 0;
                box-shadow: 0 0 0 3px rgba(100,116,139,.25); transition: background .4s; }
  .status-dot.green { background: var(--green);
    box-shadow: 0 0 0 3px rgba(34,197,94,.25), 0 0 8px rgba(34,197,94,.5); }
  .status-dot.red   { background: var(--red); box-shadow: 0 0 0 3px rgba(239,68,68,.25); }
  .status-dot.yellow{ background: var(--yellow); box-shadow: 0 0 0 3px rgba(245,158,11,.25); }
  .conn-label { font-size: .85rem; color: var(--muted); }

  /* Grid */
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px,1fr));
          gap: 16px; margin-bottom: 24px; }

  /* Card */
  .card { background: var(--card); border: 1px solid var(--border);
          border-radius: 12px; padding: 20px; }
  .card-title { font-size: .7rem; font-weight: 700; text-transform: uppercase;
                letter-spacing: 1px; color: var(--accent); margin-bottom: 14px; }

  /* Key-value rows */
  .kv { display: flex; justify-content: space-between; align-items: flex-start;
        gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--border);
        font-size: .84rem; }
  .kv:last-child { border-bottom: none; }
  .kv-key { color: var(--muted); flex-shrink: 0; max-width: 50%; }
  .kv-val { text-align: left; word-break: break-all; color: var(--text); }
  .kv-val.ok    { color: var(--green); }
  .kv-val.error { color: var(--red); }
  .kv-val.warn  { color: var(--yellow); }
  .kv-val.mono  { font-family: monospace; font-size: .78rem; }

  /* Alerts section */
  .section-title { font-size: .9rem; font-weight: 700; color: var(--accent);
                   text-transform: uppercase; letter-spacing: 1px;
                   margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
  .badge { background: var(--accent); color: #fff; border-radius: 999px;
           font-size: .7rem; padding: 2px 8px; }

  /* Alert list */
  #alert-list { display: flex; flex-direction: column; gap: 10px; }
  .alert-card { background: var(--card); border: 1px solid var(--border);
                border-radius: 10px; padding: 0; animation: fadein .4s ease;
                overflow: hidden; }
  .alert-card.new { border-color: var(--accent); }
  @keyframes fadein { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }

  /* Alert card header bar */
  .alert-header { display: flex; align-items: center; justify-content: space-between;
                  gap: 10px; padding: 12px 16px; flex-wrap: wrap;
                  border-bottom: 1px solid var(--border); }
  .alert-title { font-weight: 700; font-size: .95rem; }
  .alert-header-right { display: flex; align-items: center; gap: 8px;
                        font-size: .78rem; color: var(--muted); flex-shrink: 0; }

  /* Alert body: structured fields */
  .alert-body { padding: 10px 16px 0; }
  .alert-field { display: flex; gap: 10px; padding: 5px 0;
                 border-bottom: 1px solid var(--border); font-size: .82rem; }
  .alert-field:last-child { border-bottom: none; }
  .af-key { color: var(--muted); flex-shrink: 0; min-width: 110px; }
  .af-val { color: var(--text); word-break: break-word; }
  .af-val.mono { font-family: 'Cascadia Code','Fira Mono',monospace; font-size: .76rem;
                 color: #94a3b8; }

  /* Raw JSON toggle */
  .raw-toggle { width: 100%; background: none; border: none; border-top: 1px solid var(--border);
                color: var(--muted); font-size: .75rem; padding: 7px 16px;
                text-align: right; cursor: pointer; display: flex; align-items: center;
                gap: 5px; transition: color .2s; }
  .raw-toggle:hover { color: var(--text); }
  .raw-arrow { transition: transform .2s; display: inline-block; }
  .raw-arrow.open { transform: rotate(90deg); }
  .raw-pre { display: none; margin: 0; padding: 10px 16px 14px;
             font-family: 'Cascadia Code','Fira Mono',monospace; font-size: .74rem;
             color: #94a3b8; white-space: pre-wrap; word-break: break-all;
             background: #080a10; border-top: 1px solid var(--border); }
  .raw-pre.open { display: block; }

  .pill { background: rgba(99,102,241,.18); color: var(--accent);
          border-radius: 6px; padding: 2px 8px; font-size: .75rem; font-weight: 500; }
  .pill.ok    { background: rgba(34,197,94,.15);  color: var(--green); }
  .pill.error { background: rgba(239,68,68,.15);  color: var(--red); }
  .pill.dup   { background: rgba(245,158,11,.15); color: var(--yellow); }

  .empty { color: var(--muted); font-size: .85rem; text-align: center;
           padding: 32px; border: 1px dashed var(--border); border-radius: 10px; }

  /* Reconnect notice */
  #disconnected-banner { display: none; text-align: center; margin-bottom: 16px;
    background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.3);
    color: var(--red); border-radius: 8px; padding: 10px 16px; font-size: .85rem; }

  /* Footer */
  footer { text-align: center; color: var(--muted); font-size: .75rem; margin-top: 40px; }

  /* Connection log */
  .conn-log-wrap { margin-top: 28px; }
  #conn-log { height: 280px; overflow-y: auto; background: #080a10;
              border: 1px solid var(--border); border-radius: 10px;
              padding: 10px 14px; font-family: 'Cascadia Code','Fira Mono',monospace;
              font-size: .76rem; display: flex; flex-direction: column; gap: 1px; }
  .log-line { padding: 2px 0; white-space: pre-wrap; word-break: break-all;
              border-bottom: 1px solid rgba(42,45,58,.35); }
  .log-line:last-child { border-bottom: none; }
  .log-line .ts  { color: #3d4466; user-select: none; margin-left: 6px; }
  .log-line.ok   .ico { color: var(--green); }
  .log-line.error .ico { color: var(--red); }
  .log-line.warn  .ico { color: var(--yellow); }
  .log-line.info  .ico { color: var(--muted); }
  .log-line.ok    .txt { color: #a7f3c0; }
  .log-line.error .txt { color: #fca5a5; }
  .log-line.warn  .txt { color: #fcd34d; }
  .log-line.info  .txt { color: #94a3b8; }
</style>
</head>
<body>

<div class="header">
  <div id="dot" class="status-dot"></div>
  <h1>🚨 Pikud Haoref → Slack</h1>
  <span id="conn-label" class="conn-label">מתחבר…</span>
</div>

<div id="disconnected-banner">
  ⚠️ חיבור ל-SSE אבד — מנסה להתחבר מחדש
</div>

<div class="grid">
  <!-- Status card -->
  <div class="card">
    <div class="card-title">סטטוס שירות</div>
    <div id="status-kv"></div>
  </div>

  <!-- Config card -->
  <div class="card">
    <div class="card-title">הגדרות</div>
    <div id="config-kv"></div>
  </div>
</div>

<!-- Alerts feed -->
<div class="section-title">
  התראות אחרונות (5 דקות)
  <span class="badge" id="alert-count">0</span>
</div>
<div id="alert-list"><div class="empty">לא התקבלו התראות עדיין</div></div>

<!-- Connection log -->
<div class="conn-log-wrap">
  <div class="section-title">לוג חיבורים לפיקוד העורף</div>
  <div id="conn-log"><div class="log-line info"><span class="ts">--:--:--</span><span class="txt"> ממתין לנתונים…</span></div></div>
</div>

<footer>pikud-haoref-daemon · <span id="last-tick">—</span></footer>

<script>
// ── Utilities ─────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const esc = s => String(s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  .replace(/"/g,'&quot;');

function fmtTime(iso) {
  if (!iso) return '—';
  try {
    return new Intl.DateTimeFormat('he-IL', {
      timeZone: 'Asia/Jerusalem',
      dateStyle: 'short', timeStyle: 'medium'
    }).format(new Date(iso));
  } catch { return iso; }
}

function maskUrl(url) {
  if (!url) return '—';
  try {
    const u = new URL(url);
    return u.protocol + '//' + u.host + '/…';
  } catch { return url.slice(0,30) + '…'; }
}

// ── KV renderer ───────────────────────────────────────────────────────────
function renderKV(container, rows) {
  container.innerHTML = rows.map(([k, v, cls]) =>
    `<div class="kv">
       <span class="kv-key">${esc(k)}</span>
       <span class="kv-val ${cls||''}">${v}</span>
     </div>`
  ).join('');
}

// ── Status card ───────────────────────────────────────────────────────────
function renderStatus(s) {
  const dot = $('dot');
  const lbl = $('conn-label');
  if (s.connected) {
    dot.className = 'status-dot green';
    lbl.textContent = 'מחובר';
    $('disconnected-banner').style.display = 'none';
  } else if (s.ready) {
    dot.className = 'status-dot yellow';
    lbl.textContent = 'מנסה להתחבר מחדש…';
  } else {
    dot.className = 'status-dot red';
    lbl.textContent = 'לא מחובר';
  }

  renderKV($('status-kv'), [
    ['הופעל',         fmtTime(s.started_at), ''],
    ['מוכן',          s.ready ? 'כן' : 'לא', s.ready ? 'ok' : 'warn'],
    ['מחובר',         s.connected ? 'כן' : 'לא', s.connected ? 'ok' : 'error'],
    ['נקודת קצה',     `<span class="mono">${esc(s.current_endpoint||'—')}</span>`, 'mono'],
    ['Keepalive אחרון', fmtTime(s.last_keepalive_at), ''],
    ['התראה אחרונה',  fmtTime(s.last_alert_at), ''],
    ['תוצאת Slack',   s.last_slack_result || '—',
      s.last_slack_result === 'ok' ? 'ok'
      : s.last_slack_result === 'error' ? 'error' : ''],
    ['חיבורים מחדש',  String(s.reconnect_count ?? 0), ''],
    ['שגיאה אחרונה',  s.last_error
      ? `<span style="color:var(--red)">${esc(s.last_error)}</span>` : '—', ''],
  ]);
}

// ── Config card ───────────────────────────────────────────────────────────
function renderConfig(c) {
  renderKV($('config-kv'), [
    ['Webhook URL', maskUrl(c.slack_webhook_url), 'mono'],
    ['SSE ראשי',    `<span class="mono">${esc(c.pikud_sse_url)}</span>`, ''],
    ['SSE גיבוי',   `<span class="mono">${esc(c.pikud_sse_fallback_url)}</span>`, ''],
    ['סינון ערים',  c.city_filters    || 'הכל', ''],
    ['סינון מחוז',  c.region_filters  || 'הכל', ''],
    ['כולל תרגילים', c.include_drills ? 'כן' : 'לא', c.include_drills ? 'warn' : ''],
    ['TTL כפילויות', `${c.dedupe_ttl_seconds}s`, ''],
    ['אזור זמן',    c.timezone, ''],
  ]);
}

// ── Alert list ────────────────────────────────────────────────────────────
let alertCount = 0;

function slackPill(result) {
  if (result === 'ok')       return '<span class="pill ok">Slack ✓</span>';
  if (result === 'error')    return '<span class="pill error">Slack ✗</span>';
  if (result === 'filtered') return '<span class="pill dup">סונן</span>';
  if (result === 'duplicate')return '<span class="pill dup">כפילות</span>';
  return '';
}

function field(key, val, mono) {
  if (!val && val !== 0) return '';
  return `<div class="alert-field">
    <span class="af-key">${esc(key)}</span>
    <span class="af-val${mono ? ' mono' : ''}">${esc(String(val))}</span>
  </div>`;
}

function renderAlertCard(a, isNew) {
  const raw   = a.raw || {};
  const time  = a.received_at_iso ? fmtTime(a.received_at_iso) : '—';

  // Prefer the parsed `type` from raw payload for the title icon/label
  const typeStr = raw.type || '';
  const title   = a.title || typeStr || 'התראה';

  // Cities: from parsed cities array, falling back to raw
  const cities = (a.cities && a.cities.length)
    ? a.cities.join(' · ')
    : (Array.isArray(raw.cities) ? raw.cities.join(' · ') : '');

  // Instructions from raw (pikud-haoref-api field).
  // Suppress if identical to the title — same logic as Slack's _clean_instructions().
  const _instructions = raw.instructions || a.description || '';
  const instructions = _instructions.trim() !== title.trim() ? _instructions : '';

  const alertId = raw.id || a.alert_id || '';
  const endpoint = a.endpoint || '';

  // Pretty-print raw JSON
  const rawJson = JSON.stringify(raw, null, 2);
  const uid = 'r' + Math.random().toString(36).slice(2);

  return `
    <div class="alert-card ${isNew ? 'new' : ''}">
      <div class="alert-header">
        <div class="alert-title">${esc(title)}</div>
        <div class="alert-header-right">
          ${slackPill(a.slack_result)}
          <span>🕐 ${esc(time)}</span>
        </div>
      </div>
      <div class="alert-body">
        ${field('סוג (type)',    typeStr,       true)}
        ${field('ערים',          cities,        false)}
        ${field('הנחיות',        instructions,  false)}
        ${field('מזהה (id)',     alertId,       true)}
        ${endpoint ? field('נקודת קצה', endpoint, true) : ''}
      </div>
      <button class="raw-toggle" onclick="toggleRaw('${uid}')">
        <span class="raw-arrow" id="arr-${uid}">▶</span> Raw JSON
      </button>
      <pre class="raw-pre" id="pre-${uid}">${esc(rawJson)}</pre>
    </div>`;
}

function toggleRaw(uid) {
  const pre = document.getElementById('pre-' + uid);
  const arr = document.getElementById('arr-' + uid);
  pre.classList.toggle('open');
  arr.classList.toggle('open');
}

function prependAlert(a) {
  const list = $('alert-list');
  // Remove empty placeholder
  const empty = list.querySelector('.empty');
  if (empty) empty.remove();

  alertCount++;
  $('alert-count').textContent = alertCount;

  list.insertAdjacentHTML('afterbegin', renderAlertCard(a, true));
  // Remove new class after animation
  setTimeout(() => {
    const first = list.firstElementChild;
    if (first) first.classList.remove('new');
  }, 1500);

  // Keep at most 200 cards in DOM (safety cap)
  while (list.children.length > 200) list.removeChild(list.lastChild);
}

function populateAlerts(alerts) {
  if (!alerts.length) return;
  const list = $('alert-list');
  list.innerHTML = alerts.map(a => renderAlertCard(a, false)).join('');
  alertCount = alerts.length;
  $('alert-count').textContent = alertCount;
}

// ── Connection log ─────────────────────────────────────────────────────────────────

const LOG_ICO = { ok: '▶', error: '✗', warn: '⚠', info: '•' };

function renderLogLine(e) {
  const ico = LOG_ICO[e.level] || '•';
  return `<div class="log-line ${esc(e.level)}">`
       + `<span class="ico">${ico} </span>`
       + `<span class="ts">${esc(e.ts_iso)}</span> `
       + `<span class="txt">${esc(e.msg)}</span>`
       + `</div>`;
}

function prependLog(entry) {
  const wrap = $('conn-log');
  // Remove placeholder
  const placeholder = wrap.querySelector('.log-line.info span.txt');
  if (placeholder && placeholder.textContent.includes('ממתין')) wrap.innerHTML = '';
  wrap.insertAdjacentHTML('afterbegin', renderLogLine(entry));
  // Cap DOM entries
  while (wrap.children.length > 150) wrap.removeChild(wrap.lastChild);
}

function populateLogs(entries) {
  if (!entries.length) return;
  $('conn-log').innerHTML = entries.map(renderLogLine).join('');
}

// ── Initial data load ─────────────────────────────────────────────────────
async function load() {
  try {
    const [s, c, a, l] = await Promise.all([
      fetch('/api/status').then(r => r.json()),
      fetch('/api/config').then(r => r.json()),
      fetch('/api/alerts').then(r => r.json()),
      fetch('/api/logs').then(r => r.json()),
    ]);
    renderStatus(s);
    renderConfig(c);
    populateAlerts(a);
    populateLogs(l);
  } catch (e) { console.warn('Initial load failed', e); }
}

// ── Live SSE from server ──────────────────────────────────────────────────
let evtSource;
function connectSSE() {
  evtSource = new EventSource('/events');

  evtSource.addEventListener('status', e => {
    renderStatus(JSON.parse(e.data));
    $('last-tick').textContent = fmtTime(new Date().toISOString());
  });

  evtSource.addEventListener('alert', e => {
    prependAlert(JSON.parse(e.data));
    $('last-tick').textContent = fmtTime(new Date().toISOString());
  });

  evtSource.addEventListener('ping', () => {
    $('last-tick').textContent = fmtTime(new Date().toISOString());
  });

  evtSource.addEventListener('log', e => {
    prependLog(JSON.parse(e.data));
  });

  evtSource.onerror = () => {
    $('disconnected-banner').style.display = 'block';
    // Browser auto-retries EventSource; we just show the banner
  };

  evtSource.onopen = () => {
    $('disconnected-banner').style.display = 'none';
  };
}

load().then(connectSSE);

// ── Polling fallback (catches updates when SSE drops) ─────────────────────
let _lastAlertId = null;
setInterval(async () => {
  try {
    const alerts = await fetch('/api/alerts').then(r => r.json());
    if (!alerts.length) return;
    const newest = alerts[0].rowid || alerts[0].received_at;
    if (_lastAlertId === null) { _lastAlertId = newest; return; }
    if (newest !== _lastAlertId) {
      _lastAlertId = newest;
      populateAlerts(alerts);
      alertCount = alerts.length;
      $('alert-count').textContent = alertCount;
    }
    const logs = await fetch('/api/logs').then(r => r.json());
    if (logs.length) populateLogs(logs);
    const status = await fetch('/api/status').then(r => r.json());
    renderStatus(status);
  } catch(e) { /* silent */ }
}, 20000);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_root(request: web.Request) -> web.Response:
    return web.Response(
        text=_HTML,
        content_type="text/html",
        charset="utf-8",
    )


async def handle_status(request: web.Request) -> web.Response:
    status_store = request.app["status_store"]
    return web.json_response(status_store.get())


async def handle_config(request: web.Request) -> web.Response:
    settings = request.app["settings"]

    def mask(url: str) -> str:
        if not url or url.startswith("https://hooks.slack.com/services/XXX"):
            return "(not configured)"
        return url[:20] + "…" + url[-8:] if len(url) > 30 else url

    data = {
        "slack_webhook_url": mask(settings.slack_webhook_url),
        "pikud_sse_url": settings.pikud_sse_url,
        "pikud_sse_fallback_url": settings.pikud_sse_fallback_url,
        "city_filters": settings.city_filters or "",
        "region_filters": settings.region_filters or "",
        "include_drills": settings.include_drills,
        "dedupe_ttl_seconds": settings.dedupe_ttl_seconds,
        "db_path": settings.db_path,
        "timezone": settings.timezone,
        "log_level": settings.log_level,
        "web_port": settings.web_port,
    }
    return web.json_response(data)


async def handle_alerts(request: web.Request) -> web.Response:
    alert_log = request.app["alert_log"]
    return web.json_response(alert_log.recent_minutes(5))


async def handle_logs(request: web.Request) -> web.Response:
    conn_log = request.app["conn_log"]
    return web.json_response(conn_log.recent(100))


async def handle_events(request: web.Request) -> web.StreamResponse:
    """SSE endpoint for the browser dashboard."""
    broadcaster: Broadcaster = request.app["broadcaster"]
    q = broadcaster.add_client()

    resp = web.StreamResponse()
    resp.headers["Content-Type"] = "text/event-stream"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    await resp.prepare(request)

    # Send current status immediately on connect
    status_store = request.app["status_store"]
    init = f"event: status\ndata: {json.dumps(status_store.get(), ensure_ascii=False)}\n\n"
    await resp.write(init.encode("utf-8"))

    try:
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=15.0)
                await resp.write(chunk.encode("utf-8"))
            except TimeoutError:
                # Keep-alive ping
                await resp.write(b"event: ping\ndata: {}\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        broadcaster.remove_client(q)

    return resp


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    settings, status_store, alert_log, broadcaster: Broadcaster, conn_log: ConnectionLogger
) -> web.Application:
    app = web.Application()
    app["settings"] = settings
    app["status_store"] = status_store
    app["alert_log"] = alert_log
    app["broadcaster"] = broadcaster
    app["conn_log"] = conn_log

    app.router.add_get("/", handle_root)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/config", handle_config)
    app.router.add_get("/api/alerts", handle_alerts)
    app.router.add_get("/api/logs", handle_logs)
    app.router.add_get("/events", handle_events)

    return app


async def run_web_server(
    settings,
    status_store,
    alert_log,
    broadcaster: Broadcaster,
    conn_log: ConnectionLogger,
) -> None:
    app = create_app(settings, status_store, alert_log, broadcaster, conn_log)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.web_host, settings.web_port)
    try:
        await site.start()
    except OSError as exc:
        log.error(
            "Dashboard could not bind to %s:%s – %s  "
            "(is another instance already running?)",
            settings.web_host, settings.web_port, exc,
        )
        await runner.cleanup()
        return  # web server is optional – daemon keeps running
    log.info(
        "Dashboard → http://localhost:%s  (bind %s)",
        settings.web_port, settings.web_host,
    )
    # Keep running until cancelled
    try:
        await asyncio.get_running_loop().create_future()  # run forever
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()
