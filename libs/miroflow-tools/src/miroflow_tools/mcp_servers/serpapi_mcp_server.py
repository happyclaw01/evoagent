# Copyright (c) 2025 MiroMind
# This source code is licensed under the MIT License.

"""
SerpAPI MCP Server — multi-engine search (Google, Bing, Baidu, Yahoo, Yandex, etc.)
via serpapi.com.
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
    response = requests.get(f"{SERPAPI_BASE_URL}/search.json", params=params, timeout=30)
    response.raise_for_status()
    return response


def _is_huggingface_dataset_or_space_url(url: str) -> bool:
    if not url:
        return False
    return "huggingface.co/datasets" in url or "huggingface.co/spaces" in url


def _normalize_results(data: Dict[str, Any], engine: str) -> Dict[str, Any]:
    """Normalize SerpAPI response to a structure similar to Serper output
    so downstream code can handle it uniformly."""
    normalized: Dict[str, Any] = {
        "searchParameters": {
            "q": data.get("search_parameters", {}).get("q", ""),
            "engine": engine,
        },
    }

    # --- organic results ---
    organic_raw = data.get("organic_results", [])
    organic = []
    for item in organic_raw:
        link = item.get("link", "")
        if _is_huggingface_dataset_or_space_url(link):
            continue
        organic.append({
            "title": item.get("title", ""),
            "link": link,
            "snippet": item.get("snippet", ""),
            "position": item.get("position"),
        })
    normalized["organic"] = organic

    # --- knowledge graph ---
    kg = data.get("knowledge_graph")
    if kg:
        normalized["knowledgeGraph"] = {
            "title": kg.get("title", ""),
            "type": kg.get("type", ""),
            "description": kg.get("description", ""),
            "website": kg.get("website", ""),
        }

    # --- answer box ---
    ab = data.get("answer_box")
    if ab:
        normalized["answerBox"] = {
            "title": ab.get("title", ""),
            "answer": ab.get("answer", ab.get("snippet", "")),
        }

    # --- related searches ---
    related = data.get("related_searches", [])
    if related:
        normalized["relatedSearches"] = [
            {"query": r.get("query", "")} for r in related
        ]

    return normalized


# ---------------------------------------------------------------------------
# Google search (default)
# ---------------------------------------------------------------------------
@mcp.tool()
def serpapi_google_search(
    q: str,
    gl: str = "us",
    hl: str = "en",
    location: Optional[str] = None,
    num: int = 10,
    tbs: Optional[str] = None,
) -> Dict[str, Any]:
    """Search Google via SerpAPI. Returns organic results, knowledge graph,
    answer box, and related searches.

    Args:
        q: Search query string.
        gl: Country code (e.g. 'us', 'cn', 'uk').
        hl: Language code (e.g. 'en', 'zh-cn').
        location: Optional city-level location (e.g. 'Austin, Texas, United States').
        num: Number of results (default 10).
        tbs: Time filter ('qdr:h', 'qdr:d', 'qdr:w', 'qdr:m', 'qdr:y').

    Returns:
        Normalized search results dictionary.
    """
    if not SERPAPI_API_KEY:
        return {"success": False, "error": "SERPAPI_API_KEY not set", "results": []}

    params: Dict[str, Any] = {
        "engine": "google",
        "q": q.strip(),
        "gl": gl,
        "hl": hl,
        "num": num,
        "api_key": SERPAPI_API_KEY,
        "output": "json",
    }
    if location:
        params["location"] = location
    if tbs:
        params["tbs"] = tbs

    try:
        response = _make_serpapi_request(params)
        data = response.json()
        if "error" in data:
            return {"success": False, "error": data["error"], "results": []}
        result = _normalize_results(data, "google")
        return decode_http_urls_in_dict(result)
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}", "results": []}


# ---------------------------------------------------------------------------
# Bing search
# ---------------------------------------------------------------------------
@mcp.tool()
def serpapi_bing_search(
    q: str,
    cc: str = "US",
    setlang: str = "en",
    count: int = 10,
    first: int = 1,
) -> Dict[str, Any]:
    """Search Bing via SerpAPI. Useful for cross-engine verification.

    Args:
        q: Search query string.
        cc: Country code (e.g. 'US', 'CN', 'GB').
        setlang: Language (e.g. 'en', 'zh-cn').
        count: Number of results (default 10).
        first: Starting position (default 1).

    Returns:
        Normalized search results dictionary.
    """
    if not SERPAPI_API_KEY:
        return {"success": False, "error": "SERPAPI_API_KEY not set", "results": []}

    params: Dict[str, Any] = {
        "engine": "bing",
        "q": q.strip(),
        "cc": cc,
        "setlang": setlang,
        "count": count,
        "first": first,
        "api_key": SERPAPI_API_KEY,
        "output": "json",
    }

    try:
        response = _make_serpapi_request(params)
        data = response.json()
        if "error" in data:
            return {"success": False, "error": data["error"], "results": []}
        result = _normalize_results(data, "bing")
        return decode_http_urls_in_dict(result)
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}", "results": []}


# ---------------------------------------------------------------------------
# Baidu search
# ---------------------------------------------------------------------------
@mcp.tool()
def serpapi_baidu_search(
    q: str,
    ct: str = "0",
    rn: int = 10,
) -> Dict[str, Any]:
    """Search Baidu via SerpAPI. Best for Chinese-language queries.

    Args:
        q: Search query string (supports Chinese).
        ct: Content type filter ('0' for all, '1' for news, '2' for web pages).
        rn: Number of results (default 10).

    Returns:
        Normalized search results dictionary.
    """
    if not SERPAPI_API_KEY:
        return {"success": False, "error": "SERPAPI_API_KEY not set", "results": []}

    params: Dict[str, Any] = {
        "engine": "baidu",
        "q": q.strip(),
        "ct": ct,
        "rn": rn,
        "api_key": SERPAPI_API_KEY,
        "output": "json",
    }

    try:
        response = _make_serpapi_request(params)
        data = response.json()
        if "error" in data:
            return {"success": False, "error": data["error"], "results": []}
        result = _normalize_results(data, "baidu")
        return decode_http_urls_in_dict(result)
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}", "results": []}


# ---------------------------------------------------------------------------
# Yahoo search
# ---------------------------------------------------------------------------
@mcp.tool()
def serpapi_yahoo_search(
    p: str,
    vl: str = "lang_en",
    vc: str = "us",
    n: int = 10,
) -> Dict[str, Any]:
    """Search Yahoo via SerpAPI.

    Args:
        p: Search query string.
        vl: Language filter (e.g. 'lang_en', 'lang_zh').
        vc: Country filter (e.g. 'us', 'cn').
        n: Number of results (default 10).

    Returns:
        Normalized search results dictionary.
    """
    if not SERPAPI_API_KEY:
        return {"success": False, "error": "SERPAPI_API_KEY not set", "results": []}

    params: Dict[str, Any] = {
        "engine": "yahoo",
        "p": p.strip(),
        "vl": vl,
        "vc": vc,
        "n": n,
        "api_key": SERPAPI_API_KEY,
        "output": "json",
    }

    try:
        response = _make_serpapi_request(params)
        data = response.json()
        if "error" in data:
            return {"success": False, "error": data["error"], "results": []}
        result = _normalize_results(data, "yahoo")
        return decode_http_urls_in_dict(result)
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}", "results": []}


# ---------------------------------------------------------------------------
# Yandex search
# ---------------------------------------------------------------------------
@mcp.tool()
def serpapi_yandex_search(
    text: str,
    lr: str = "84",
    lang: str = "en",
) -> Dict[str, Any]:
    """Search Yandex via SerpAPI. Good for Russian-language and Eastern European content.

    Args:
        text: Search query string.
        lr: Region code ('84' for US, '225' for Russia, '187' for Ukraine).
        lang: Language ('en', 'ru', etc.).

    Returns:
        Normalized search results dictionary.
    """
    if not SERPAPI_API_KEY:
        return {"success": False, "error": "SERPAPI_API_KEY not set", "results": []}

    params: Dict[str, Any] = {
        "engine": "yandex",
        "text": text.strip(),
        "lr": lr,
        "lang": lang,
        "api_key": SERPAPI_API_KEY,
        "output": "json",
    }

    try:
        response = _make_serpapi_request(params)
        data = response.json()
        if "error" in data:
            return {"success": False, "error": data["error"], "results": []}
        result = _normalize_results(data, "yandex")
        return decode_http_urls_in_dict(result)
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}", "results": []}


if __name__ == "__main__":
    mcp.run()
