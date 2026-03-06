# Credits

## Leon Melamud — pikud-a-oref-mcp

The core Pikud Ha'oref API integration in this project is built on top of
**Leon Melamud's** MCP server and Node.js library:

- **Repository:** https://github.com/LeonMelamud/pikud-a-oref-mcp
- **npm package:** [`pikud-haoref-api`](https://www.npmjs.com/package/pikud-haoref-api)

Leon's work handles all the complexity of polling the official Israeli Home
Front Command API, decoding the response encoding, and exposing a clean
JavaScript interface. Without it, this project would not exist.

Please ⭐ [his repository](https://github.com/LeonMelamud/pikud-a-oref-mcp).

---

## Pikud Ha'oref (Israel Home Front Command)

Alert data is sourced from the official Pikud Ha'oref public API:
https://www.oref.org.il

---

## Open source dependencies

| Package | License | Purpose |
|---|---|---|
| [`pikud-haoref-api`](https://github.com/nicklvsa/pikud-haoref) | MIT | Pikud Ha'oref API client (Leon's MCP) |
| [`@modelcontextprotocol/sdk`](https://github.com/modelcontextprotocol/typescript-sdk) | MIT | MCP server SDK |
| [`httpx`](https://github.com/encode/httpx) | BSD-3 | Async HTTP + SSE client |
| [`slack-sdk`](https://github.com/slackapi/python-slack-sdk) | MIT | Slack webhook client |
| [`pydantic-settings`](https://github.com/pydantic/pydantic-settings) | MIT | Environment-based configuration |
| [`aiohttp`](https://github.com/aio-libs/aiohttp) | Apache-2.0 | Async web dashboard |
