# SHSE MCP Server

The MCP (Model Context Protocol) server exposes the homelab search index as a
tool that Claude Code and other MCP clients can call directly.

---

## Tool API reference

### `search_lab`

```
search_lab(query: str) -> list[str]
```

Runs a BM25 multi-field search (title + text, title boosted 2×) against the
OpenSearch index and returns the top-`k` text chunks as plain strings. Each
chunk has the format:

```
<title>
<url>
<text>
```

**Parameters**

| Name | Type | Description |
|---|---|---|
| `query` | `str` | Plain-text search query |

**Returns** `list[str]` — up to `MCP_RESULT_K` chunks (default 10). Returns
`[]` when OpenSearch is unreachable; never raises.

**Transport:** streamable HTTP at `http://<host>:<port>/mcp` (MCP 1.x standard).

**Health endpoint:** `GET http://<host>:<port>/health` — returns `{"status": "ok"}`.

---

## docker-compose usage

The MCP server is an **optional service** declared under the `mcp` profile.
It is not started during a normal `docker compose up`.

```bash
# Start the full stack plus the MCP server
docker compose --profile mcp up -d

# Start only the MCP server (requires OpenSearch already running)
docker compose --profile mcp up mcp_server -d

# Stop and remove
docker compose --profile mcp down
```

The MCP server shares the same Docker image as the Flask app
(`Dockerfile.flask`). It reads env vars from `.env` and overrides
`OPENSEARCH_HOST=opensearch` for container-internal name resolution.

---

## Configuration

All variables are read at call time (not import time), so changes take effect
on the next tool invocation without a server restart.

| Variable | Default | Description |
|---|---|---|
| `MCP_HOST` | `0.0.0.0` | Bind address passed to uvicorn |
| `MCP_PORT` | `8765` | Bind port |
| `MCP_RESULT_K` | `10` | Maximum chunks returned per query |
| `OPENSEARCH_HOST` | `localhost` | OpenSearch hostname |
| `OPENSEARCH_PORT` | `9200` | OpenSearch port |
| `OPENSEARCH_INITIAL_ADMIN_PASSWORD` | — | OpenSearch admin password |

Copy `.env.example` and fill in values. The relevant block:

```bash
MCP_HOST=0.0.0.0
MCP_PORT=8765
MCP_RESULT_K=10
```

---

## How to call from Claude Code

### Add as an MCP server

Add to your Claude Code MCP configuration (`~/.claude.json` or via
`claude mcp add`):

```json
{
  "mcpServers": {
    "shse": {
      "type": "http",
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

Or with the Claude Code CLI:

```bash
claude mcp add --transport http shse http://localhost:8765/mcp
```

### Verify the connection

```bash
# Check the health endpoint
curl http://localhost:8765/health
# → {"status":"ok"}

# List tools (MCP initialize + list)
claude mcp list
# → shse: search_lab
```

### Example usage in a Claude session

Once the server is wired up, Claude can call it automatically when answering
questions about content in your homelab index:

```
User: What does my homelab wiki say about DNS configuration?
Claude: [calls search_lab("DNS configuration")] ...
```

You can also call it explicitly with a slash command:

```
/mcp shse search_lab query="DNS configuration"
```

---

## Known limitations

- Only BM25 search is used; vector (semantic) search is not wired in the MCP
  server (the embedding model may not be reachable from the MCP container).
- The server is stateless — each tool call opens a new OpenSearch connection.
- `MCP_RESULT_K` applies globally; per-call `k` overrides are not supported.
- The MCP endpoint is at `/mcp` (not `/`). Some older MCP clients that expect
  the endpoint at the root path will need a proxy or path rewrite.
