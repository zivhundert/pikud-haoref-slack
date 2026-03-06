"""Async SSE listener with primary/fallback endpoints and exponential back-off."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)


@dataclass
class SSEEvent:
    event: str
    data: str


async def _iter_sse_events(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
) -> AsyncIterator[SSEEvent | None]:
    """
    Yield SSEEvent for each complete event block, or None for keep-alive lines.

    Follows the SSE spec:
      - Lines starting with `:` are keep-alives / comments → yield None
      - `event: <name>` lines set the event type
      - `data: <value>` lines accumulate data
      - Blank line dispatches the current event
    """
    current_event = "message"
    current_data_lines: list[str] = []

    async with client.stream("GET", url, headers=headers, timeout=None) as resp:
        resp.raise_for_status()
        async for raw_line in resp.aiter_lines():
            line = raw_line  # already decoded by httpx

            if line.startswith(":"):
                # Keep-alive / comment
                yield None
                continue

            if not line:
                # Blank line → dispatch
                if current_data_lines:
                    data = "\n".join(current_data_lines)
                    yield SSEEvent(event=current_event, data=data)
                # Reset
                current_event = "message"
                current_data_lines = []
                continue

            if line.startswith("event:"):
                current_event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                current_data_lines.append(line[len("data:"):].strip())
            # Ignore `id:` and `retry:` lines for now


AlertCallback = Callable[[SSEEvent, str], Awaitable[None]]
LogCallback = Callable[[str, str], None]  # (level, message)


class SSEListener:
    """
    Connect to the primary SSE endpoint; fall back to the secondary on failure.
    Reconnects with exponential back-off (capped at 60 s).
    """

    BACKOFF_BASE = 2.0
    BACKOFF_MAX = 60.0

    def __init__(
        self,
        primary_url: str,
        fallback_url: str,
        api_key: str,
        on_event: AlertCallback,
        on_keepalive: Callable[[], None] | None = None,
        on_connected: Callable[[str], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
        on_log: LogCallback | None = None,
    ) -> None:
        self._endpoints = [primary_url, fallback_url]
        self._api_key = api_key
        self._on_event = on_event
        self._on_keepalive = on_keepalive
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_log = on_log
        self._reconnect_count = 0

    def _log(self, level: str, msg: str) -> None:
        if self._on_log:
            self._on_log(level, msg)

    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "text/event-stream"}
        if self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    async def run_forever(self) -> None:
        """Main loop: cycle through endpoints with back-off on error."""
        endpoint_idx = 0
        backoff = 1.0

        while True:
            url = self._endpoints[endpoint_idx % len(self._endpoints)]
            log.info("Connecting to SSE endpoint: %s", url)
            self._log("info", f"→ Attempting to connect to {url}")
            connected_at: float | None = None
            try:
                async with httpx.AsyncClient(
                    headers={"Accept": "text/event-stream"},
                    follow_redirects=True,
                ) as client:
                    connected_at = asyncio.get_event_loop().time()
                    if self._on_connected:
                        self._on_connected(url)
                    self._log("ok", f"← Connected to {url}")
                    async for event in _iter_sse_events(client, url, self._headers()):
                        if event is None:
                            self._log("info", f"← :keepalive from {url}")
                            if self._on_keepalive:
                                self._on_keepalive()
                        else:
                            preview = event.data[:120].replace("\n", " ")
                            self._log(
                                "ok",
                                f"← SSE event type={event.event!r}  data={preview}",
                            )
                            await self._on_event(event, url)

            except httpx.HTTPStatusError as exc:
                msg = f"✗ HTTP {exc.response.status_code} from {url}"
                log.warning("HTTP error on %s: %s", url, exc)
                self._log("error", msg)
            except httpx.RequestError as exc:
                short = str(exc).split("\n")[0][:120]
                log.warning("Request error on %s: %s", url, exc)
                self._log("error", f"✗ Connection error to {url}: {short}")
            except asyncio.CancelledError:
                log.info("SSE listener cancelled — shutting down")
                raise
            except Exception as exc:
                log.error("Unexpected error on %s: %s", url, exc, exc_info=True)
                self._log("error", f"✗ Unexpected error: {exc}")

            if self._on_disconnected:
                self._on_disconnected()

            # Only reset backoff if we stayed connected for >5 s (real stream)
            if connected_at is not None:
                duration = asyncio.get_event_loop().time() - connected_at
                if duration > 5.0:
                    backoff = 1.0

            self._reconnect_count += 1
            # Alternate endpoint on each retry
            endpoint_idx += 1

            wait = min(backoff, self.BACKOFF_MAX)
            next_url = self._endpoints[endpoint_idx % len(self._endpoints)]
            log.info(
                "Reconnecting in %.1fs (attempt %d, next endpoint: %s)",
                wait,
                self._reconnect_count,
                next_url,
            )
            self._log("warn", f"⟳ Reconnecting in {wait:.1f}s → {next_url}")
            await asyncio.sleep(wait)
            backoff = min(backoff * self.BACKOFF_BASE, self.BACKOFF_MAX)
