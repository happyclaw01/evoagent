# Copyright (c) 2025 MiroMind
# This source code is licensed under the MIT License.

"""
SerpAPI MCP Server — Baidu search via serpapi.com.
Google/Bing search is handled by Serper.dev (serper_mcp_server.py).
"""

import os
from typing import Any, Dict, Optional

import requests
from mcp.server.fastmcp import FastMCP
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .utils import decode_http_urls_in_dict

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")
SERPAPI_BASE_URL = os.getenv("SERPAPI_BASE_URL", "https://serpapi.com")

# Initialize FastMCP server
mcp = FastMCP("serpapi-mcp-server")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(
        (requests.ConnectionError, requests.Timeout, requests.HTTPError)
    ),
)
def _make_serpapi_request(params: Dict[str, Any]) -> requests.Response:
    """Make HTTP request to SerpAPI with retry logic."""
    response = requests.get(
        f"{SERPAPI_BASE_URL}/search.json", params=params, timeout=30
    )
    response.raise_for_status()
    return response


def _is_huggingface_dataset_or_space_url(url: str) -> bool:
    if not url:
        return False
    return "huggingface.co/datasets" in url or "huggingface.co/spaces" in url


def _normalize_results(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize SerpAPI Baidu response to a structure similar to Serper output."""
    normalized: Dict[str, Any] = {
        "searchParameters": {
            "q": data.get("search_parameters", {}).get("q", ""),
            "engine": "baidu",
        },
    }

    # --- organic results ---
    organic_raw = data.get("organic_results", [])
    organic = []
    for item in organic_raw:
        link = item.get("link", "")
        if _is_huggingface_dataset_or_space_url(link):
            continue
        organic.append(
            {
                "title": item.get("title", ""),
                "link": link,
                "snippet": item.get("snippet", ""),
                "position": item.get("position"),
            }
        )
    normalized["organic"] = organic

    # --- knowledge graph ---
    kg = data.get("knowledge_graph")
    if kg:
        normalized["knowledgeGraph"] = {
            "title": kg.get("title", ""),
            "type": kg.get("type", ""),
            "description": kg.get("description", ""),
        }

    # --- related searches ---
    related = data.get("related_searches", [])
    if related:
        normalized["relatedSearches"] = [
            {"query": r.get("query", "")} for r in related
        ]

    return normalized


@mcp.tool()
def baidu_search(
    q: str,
    rn: int = 10,
    pn: int = 0,
) -> Dict[str, Any]:
    """Search Baidu via SerpAPI. Best for Chinese-language queries and China-specific information.
    Use this when the query is in Chinese, or when searching for information
    specific to China (e.g., Chinese companies, events, regulations, celebrities).

    Args:
        q: Search query string (supports Chinese characters).
        rn: Number of results per page (default 10, max 50).
        pn: Result offset for pagination (default 0; use 10 for page 2, 20 for page 3, etc.).

    Returns:
        Dictionary containing search results with organic listings.
    """
    if not SERPAPI_API_KEY:
        return {"success": False, "error": "SERPAPI_API_KEY not set", "results": []}

    if not q or not q.strip():
        return {
            "success": False,
            "error": "Search query 'q' is required and cannot be empty",
            "results": [],
        }

    params: Dict[str, Any] = {
        "engine": "baidu",
        "q": q.strip(),
        "rn": min(rn, 50),
        "pn": pn,
        "api_key": SERPAPI_API_KEY,
        "output": "json",
    }

    try:
        response = _make_serpapi_request(params)
        data = response.json()
        if "error" in data:
            return {"success": False, "error": data["error"], "results": []}
        result = _normalize_results(data)
        return decode_http_urls_in_dict(result)
    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "results": [],
        }


if __name__ == "__main__":
    mcp.run()
