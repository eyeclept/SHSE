"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    SHSE MCP Server. Exposes the homelab search index as a Model Context
    Protocol (MCP) tool server using FastMCP over streamable HTTP transport.

    Tool: search_lab(query: str) -> list[str]
        Runs a BM25 query against the OpenSearch index and returns the top-k
        text chunks as plain strings, suitable for use as LLM context.

    Transport: streamable HTTP at /mcp (MCP 1.x standard).
    Start with: uvicorn mcp_server.main:app --host 0.0.0.0 --port 8765

    Environment variables read at call time (not import time):
        OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER,
        OPENSEARCH_INITIAL_ADMIN_PASSWORD
        MCP_RESULT_K  — number of chunks to return (default 10)
"""
# Imports
import logging
import os

from mcp.server.fastmcp import FastMCP

# Globals
logger = logging.getLogger(__name__)

# ── FastAPI wrapper so we can add a /health route alongside the MCP app ──
from fastapi import FastAPI as _FastAPI
from starlette.routing import Mount as _Mount

_web = _FastAPI(title="SHSE MCP Server")

_mcp = FastMCP(
    "shse",
    instructions=(
        "Search the SHSE homelab index. Call search_lab with a plain-text "
        "query; it returns the most relevant text chunks from the index."
    ),
)

_DEFAULT_K = 10


# Functions
def _run_bm25(query: str, k: int, client=None) -> list[str]:
    """
    Input: query — search string; k — result count; client — optional OS client
    Output: list of text chunk strings (may be empty if OpenSearch unreachable)
    Details:
        Imports the opensearch service at call time so the module can be
        imported without a live OpenSearch connection.
    """
    try:
        from flask_app.services.opensearch import bm25_search
        hits = bm25_search(query, k=k, client=client)
        chunks = []
        for hit in hits:
            src = hit.get("_source", {})
            title = src.get("title", "")
            text = src.get("text", "")
            url = src.get("url", "")
            chunk = f"{title}\n{url}\n{text}".strip()
            if chunk:
                chunks.append(chunk)
        return chunks
    except Exception:
        logger.warning("search_lab: OpenSearch query failed", exc_info=True)
        return []


@_mcp.tool()
def search_lab(query: str) -> list[str]:
    """
    Input: query — plain-text search query
    Output: list of text chunks from the SHSE homelab index
    Details:
        Runs a BM25 multi-field search (title + text) across the index.
        Returns up to MCP_RESULT_K chunks formatted as 'title\\nurl\\ntext'.
        Returns an empty list when OpenSearch is unreachable (silent fallback).
    """
    k = int(os.environ.get("MCP_RESULT_K", _DEFAULT_K))
    return _run_bm25(query, k)


@_web.get("/health")
def health():
    return {"status": "ok"}


# Mount the MCP streamable-HTTP handler under /mcp; expose the FastAPI app
# so /health and /mcp both work under one uvicorn process.
_mcp_starlette = _mcp.streamable_http_app()
_web.mount("/mcp", _mcp_starlette)

app = _web


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", 8765))
    uvicorn.run("mcp_server.main:app", host=host, port=port, reload=False)
