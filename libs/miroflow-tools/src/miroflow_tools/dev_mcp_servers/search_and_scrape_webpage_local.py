# Local search MCP server - uses DuckDuckGo instead of Serper
# Copyright (c) 2025 MiroMind (modified for local use)

import logging
import os
from datetime import datetime
from typing import Any, Dict

import httpx
from duckduckgo_search import DDGS
from mcp.server.fastmcp import FastMCP

from ..mcp_servers.utils.url_unquote import decode_http_urls_in_dict

logger = logging.getLogger("miroflow")

JINA_BASE_URL = os.getenv("JINA_BASE_URL", "https://r.jina.ai")
JINA_API_KEY = os.getenv("JINA_API_KEY", "")

mcp = FastMCP("search_and_scrape_webpage")


async def _ddg_search(query: str, num_results: int = 10) -> list:
    """Search using DuckDuckGo."""
    try:
        with DDGS(proxy=os.environ.get("HTTPS_PROXY", None)) as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
        return results
    except Exception as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        return []


def _format_ddg_results(results: list, query: str) -> dict:
    """Format DDG results to match Serper-like format."""
    organic = []
    for i, r in enumerate(results):
        organic.append({
            "title": r.get("title", ""),
            "link": r.get("href", r.get("link", "")),
            "snippet": r.get("body", r.get("snippet", "")),
            "position": i + 1,
        })
    return {
        "searchParameters": {"q": query},
        "organic": organic,
    }


@mcp.tool()
async def google_search(
    q: str,
    num: int = 10,
    date_range: str = "",
    site: str = "",
    filetype: str = "",
) -> str:
    """Search the web using DuckDuckGo (Google alternative).

    Args:
        q: The search query string.
        num: Number of results to return (default 10, max 20).
        date_range: Optional date range filter (e.g., 'past_week', 'past_month').
        site: Optional site filter (e.g., 'reddit.com').
        filetype: Optional file type filter (e.g., 'pdf').

    Returns:
        JSON string containing search results.
    """
    import json

    # Build query with filters
    full_query = q
    if site:
        full_query += f" site:{site}"
    if filetype:
        full_query += f" filetype:{filetype}"

    num = min(num, 20)
    results = await _ddg_search(full_query, num)
    formatted = _format_ddg_results(results, q)

    # Format output
    output_lines = []
    output_lines.append(f"Search results for: {q}")
    output_lines.append(f"Number of results: {len(formatted['organic'])}")
    output_lines.append("")

    for item in formatted["organic"]:
        output_lines.append(f"Title: {item['title']}")
        output_lines.append(f"URL: {item['link']}")
        output_lines.append(f"Snippet: {item['snippet']}")
        output_lines.append("")

    return "\n".join(output_lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
