"""
Author: Richard Baldwin
Date:   2024
Email: eyeclept@pm.me

Description: MCP server FastAPI application and tool definitions
"""


def search_homelab(query):
    """
    Input: query (str) - User search query
    Output: list[str] - Top-k text chunks as context strings
    Details: Runs BM25 + optional vector query against ES index.
             Exposed as MCP tool for OpenWebUI, Continue, or other MCP clients.
    """
    pass


def setup_mcp_routes():
    """
    Input: None
    Output: None
    Details: Register MCP tool endpoint: search_homelab(query: str) -> list[str]
    """
    pass
