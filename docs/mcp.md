# Built-in MCP server

Spoolman NG can serve your filament inventory to AI assistants — Claude Desktop,
claude.ai, Claude Code, and any other [MCP](https://modelcontextprotocol.io/)
client — directly from the running server at **`http://<your-spoolman>/mcp`**.
No separate deployment, no Node process, and **no AI provider**: the MCP server
needs nothing from [AI provider setup](ai.md) and works entirely on its own.

Off by default. Enable it under **Settings → AI → MCP server**; until then the
endpoint answers 404.

## Connecting a client

The settings page shows the connector URL and a **Copy config** button that emits
a ready-to-paste client block:

```json
{
  "mcpServers": {
    "spoolman": {
      "type": "http",
      "url": "http://spoolman.local:7912/mcp"
    }
  }
}
```

- **Claude Desktop**: paste into `claude_desktop_config.json`.
- **claude.ai**: add a custom connector with the URL (the instance must be
  reachable from where the client runs — for claude.ai that means exposing it,
  e.g. via a tunnel; on a pure LAN install prefer Claude Desktop/Claude Code).
- **Claude Code**: `claude mcp add --transport http spoolman http://spoolman.local:7912/mcp`

### Authentication

The endpoint follows the API's opt-in auth model exactly:

- Default no-auth install: no credentials needed.
- With `SPOOLMAN_API_TOKEN` or user accounts configured: send
  `Authorization: Bearer <token>` (the API token, or a login token). The copied
  config includes the header with a placeholder when auth is active.
- **Read-only accounts get read-only tools**: mutating tools are not listed for
  them and cannot be called — a hidden tool is indistinguishable from a
  nonexistent one.

## What it exposes

A curated tool surface (not blind CRUD), shared with the upcoming in-app chat
assistant — same implementations, same behavior as the web UI (usage events,
live updates, weight math all included):

| Tool | Kind | Purpose |
|---|---|---|
| `find_spools` | read | Search spools with filters (material, vendor, location, ...) |
| `find_filaments` | read | Search filament types, with spool counts and remaining weight |
| `get_inventory_stats` | read | Totals and breakdowns by material and location |
| `get_low_stock` | read | Filaments at or below their low-stock threshold |
| `use_spool_filament` | write | Log consumption by weight or length |
| `measure_spool` | write | Report a gross scale reading; usage is computed |
| `create_spool` | write | Register a new spool of an existing filament |
| `archive_spool` | write | Archive/unarchive a spool |

Plus two **resources** (`spoolman://inventory-summary`, `spoolman://low-stock` —
markdown reports) and a **prompt** (`restock_advisor`) that embeds the live
low-stock report into a reorder-advice request.

## Relationship to spoolman-mcp

The community [Disane87/spoolman-mcp](https://github.com/Disane87/spoolman-mcp)
project remains a fine choice when you want full 1:1 CRUD coverage of the REST
API. The built-in server is the batteries-included path: zero extra deployment,
version-locked to your Spoolman by construction, role-aware, and curated for
conversational use.

## Protocol notes

The server implements the stateless subset of MCP's streamable-HTTP transport
(protocol versions 2024-11-05 through 2025-06-18): single JSON-RPC messages over
`POST /mcp` with plain JSON responses, no sessions, no server-initiated streams
(`GET /mcp` answers 405, per the spec, and JSON-RPC batching is not accepted).
This is exactly what request-response tool clients use; it is implemented
in-repo with no SDK dependency and covered by contract tests.
