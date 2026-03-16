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


async def _ddg_search(query: str, num_results: int = 10, timelimit: str | None = None) -> list:
    """Search using DuckDuckGo.

    Args:
        query: Search query string.
        num_results: Max number of results.
        timelimit: Date filter. Preset values: 'd' (day), 'w' (week), 'm' (month), 'y' (year).
                   Custom range: 'YYYY-MM-DD..YYYY-MM-DD' (e.g. '2024-01-01..2026-01-18').
    """
    try:
        with DDGS(proxy=os.environ.get("HTTPS_PROXY", None)) as ddgs:
            results = list(ddgs.text(query, max_results=num_results, timelimit=timelimit))
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


def _parse_timelimit(date_range: str = "", before_date: str = "") -> str | None:
    """Convert date_range or before_date into a DuckDuckGo timelimit value.

    Args:
        date_range: Preset filter like 'past_day', 'past_week', 'past_month', 'past_year',
                    or shorthand 'd', 'w', 'm', 'y'.
        before_date: Cut-off date in 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' format.
                     Results will be limited to before this date.

    Returns:
        A timelimit string for DuckDuckGo, or None if no filter.
    """
    # Preset mappings
    preset_map = {
        "past_day": "d", "past_week": "w", "past_month": "m", "past_year": "y",
        "d": "d", "w": "w", "m": "m", "y": "y",
    }

    if date_range and date_range in preset_map:
        return preset_map[date_range]

    # Custom before_date → range format "2020-01-01..YYYY-MM-DD"
    if before_date:
        try:
            # Parse various date formats
            clean = before_date.strip().split(" ")[0]  # Take date part only
            dt = datetime.strptime(clean, "%Y-%m-%d")
            return f"2020-01-01..{dt.strftime('%Y-%m-%d')}"
        except ValueError:
            logger.warning(f"Invalid before_date format: {before_date}")

    return None


@mcp.tool()
async def google_search(
    q: str,
    num: int = 10,
    date_range: str = "",
    before_date: str = "",
    site: str = "",
    filetype: str = "",
) -> str:
    """Search the web using DuckDuckGo (Google alternative).

    Args:
        q: The search query string.
        num: Number of results to return (default 10, max 20).
        date_range: Optional date range filter (e.g., 'past_day', 'past_week', 'past_month', 'past_year').
        before_date: Optional cut-off date (YYYY-MM-DD). Only return results published before this date.
                     Useful for predicting future events — prevents seeing results after the event resolved.
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

    # Resolve timelimit from date_range or before_date
    timelimit = _parse_timelimit(date_range=date_range, before_date=before_date)

    num = min(num, 20)
    results = await _ddg_search(full_query, num, timelimit=timelimit)
    formatted = _format_ddg_results(results, q)

    # Format output
    output_lines = []
    output_lines.append(f"Search results for: {q}")
    if before_date:
        output_lines.append(f"Date filter: results before {before_date}")
    elif date_range:
        output_lines.append(f"Date filter: {date_range}")
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
