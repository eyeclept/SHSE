"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 15 (MCP Server): search_lab tool, server startup,
    docker-compose optional service syntax. No live stack required —
    all OpenSearch calls are mocked.
"""
# Imports
import asyncio
import subprocess
from unittest.mock import MagicMock, patch

import pytest


# Functions
def _make_hit(title="Test Title", url="http://example.com", text="Some content here."):
    return {"_source": {"title": title, "url": url, "text": text}, "_score": 1.0}


# ── search_lab tool ───────────────────────────────────────────────────────

def test_search_lab_returns_list_of_strings():
    """
    Input: search_lab called with a query; bm25_search mocked to return two hits
    Output: list of non-empty strings, one per hit
    """
    from mcp_server.main import _mcp

    mock_hits = [
        _make_hit("Alpha", "http://a.test", "Alpha body text."),
        _make_hit("Beta", "http://b.test", "Beta body text."),
    ]
    with patch("mcp_server.main._run_bm25", return_value=["Alpha\nhttp://a.test\nAlpha body text.",
                                                           "Beta\nhttp://b.test\nBeta body text."]):
        result, _meta = asyncio.run(
            _mcp.call_tool("search_lab", {"query": "test query"})
        )

    texts = [item.text for item in result]
    assert isinstance(texts, list)
    assert len(texts) == 2
    assert any("Alpha" in t for t in texts)
    assert any("Beta" in t for t in texts)


def test_search_lab_empty_when_opensearch_down():
    """
    Input: bm25_search raises an exception (OpenSearch unreachable)
    Output: empty list returned; no exception propagates
    """
    from mcp_server.main import _run_bm25

    with patch("flask_app.services.opensearch.bm25_search", side_effect=ConnectionError("down")):
        result = _run_bm25("test", k=5)

    assert result == []


def test_run_bm25_formats_chunks_correctly():
    """
    Input: bm25_search returns two raw hits
    Output: each chunk contains title, url, and text separated by newlines
    """
    from mcp_server.main import _run_bm25

    mock_hits = [
        _make_hit("Doc Title", "http://host/page", "Main paragraph text."),
    ]
    with patch("flask_app.services.opensearch.bm25_search", return_value=mock_hits):
        chunks = _run_bm25("query", k=10)

    assert len(chunks) == 1
    assert "Doc Title" in chunks[0]
    assert "http://host/page" in chunks[0]
    assert "Main paragraph text." in chunks[0]


# ── Server starts and responds ────────────────────────────────────────────

def test_mcp_app_is_asgi_callable():
    """
    Input: import mcp_server.main
    Output: app attribute exists and is an ASGI callable (Starlette/FastAPI)
    """
    from mcp_server.main import app
    assert callable(app)
    assert hasattr(app, "routes") or hasattr(app, "__call__")


def test_mcp_server_lists_search_lab_tool():
    """
    Input: list_tools called on the FastMCP instance
    Output: 'search_lab' appears in the tool list
    """
    from mcp_server.main import _mcp

    tools = asyncio.run(_mcp.list_tools())
    names = [t.name for t in tools]
    assert "search_lab" in names


# ── Optional docker-compose service ──────────────────────────────────────

def test_compose_config_valid_without_mcp_profile():
    """
    Input: docker compose config (no --profile mcp)
    Output: exits 0; mcp_server absent from default services
    """
    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "config", "--services"],
        capture_output=True, text=True, cwd="/home/eyeclept/Documents/Code/Projects/SHSE",
    )
    assert result.returncode == 0, result.stderr
    services = result.stdout.splitlines()
    assert "mcp_server" not in services


def test_compose_config_valid_with_mcp_profile():
    """
    Input: docker compose config --profile mcp
    Output: exits 0; mcp_server present in service list
    """
    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "--profile", "mcp",
         "config", "--services"],
        capture_output=True, text=True, cwd="/home/eyeclept/Documents/Code/Projects/SHSE",
    )
    assert result.returncode == 0, result.stderr
    services = result.stdout.splitlines()
    assert "mcp_server" in services
