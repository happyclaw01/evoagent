# Copyright (c) 2025 MiroMind
# This source code is licensed under the MIT License.

"""
High-level SerpAPI search tools exposed as FastMCP server.
Supports Google, Bing, Baidu, Yahoo, and Yandex via SerpAPI.
"""

import asyncio
import json
import os
import sys

import requests
from fastmcp import FastMCP
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .utils import strip_markdown_links

SERPAPI_API_KEY = os.environ.get("SERPAPI_API_KEY", "")
SERPAPI_BASE_URL = os.environ.get("SERPAPI_BASE_URL", "https://serpapi.com")
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")
JINA_BASE_URL = os.environ.get("JINA_BASE_URL", "https://r.jina.ai")

# Initialize FastMCP server
mcp = FastMCP("searching-serpapi-mcp-server")


async def _call_serpapi_tool(tool_name: str, arguments: dict) -> str:
    """Call a tool on the serpapi_mcp_server subprocess."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "miroflow_tools.mcp_servers.serpapi_mcp_server"],
        env={
            "SERPAPI_API_KEY": SERPAPI_API_KEY,
            "SERPAPI_BASE_URL": SERPAPI_BASE_URL,
        },
    )

    retry_count = 0
    max_retries = 3

    while retry_count < max_retries:
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write, sampling_callback=None) as session:
                    await session.initialize()
                    tool_result = await session.call_tool(tool_name, arguments=arguments)
                    result_content = (
                        tool_result.content[-1].text if tool_result.content else ""
                    )
                    assert (
                        result_content is not None and result_content.strip() != ""
                    ), f"Empty result from {tool_name}, please try again."
                    return result_content
        except Exception as error:
            retry_count += 1
            if retry_count >= max_retries:
                return f"[ERROR]: {tool_name} failed after {max_retries} attempts: {str(error)}"
            await asyncio.sleep(min(2**retry_count, 60))

    return f"[ERROR]: Unknown error in {tool_name}."


@mcp.tool()
async def serpapi_google_search(
    q: str,
    gl: str = "us",
    hl: str = "en",
    location: str = None,
    num: int = 10,
    tbs: str = None,
) -> str:
    """Search Google via SerpAPI. Returns organic results, knowledge graph, and answer box.

    Args:
        q: Search query string.
        gl: Country code (e.g. 'us', 'cn', 'uk').
        hl: Language code (e.g. 'en', 'zh-cn').
        location: Optional city-level location (e.g. 'Austin, Texas, United States').
        num: Number of results (default 10).
        tbs: Time filter ('qdr:h' past hour, 'qdr:d' past day, 'qdr:w' past week, 'qdr:m' past month, 'qdr:y' past year).

    Returns:
        JSON string with search results.
    """
    if not SERPAPI_API_KEY:
        return "[ERROR]: SERPAPI_API_KEY is not set, serpapi_google_search is unavailable."

    arguments = {"q": q, "gl": gl, "hl": hl, "num": num}
    if location:
        arguments["location"] = location
    if tbs:
        arguments["tbs"] = tbs

    return await _call_serpapi_tool("serpapi_google_search", arguments)


@mcp.tool()
async def serpapi_bing_search(
    q: str,
    cc: str = "US",
    setlang: str = "en",
    count: int = 10,
) -> str:
    """Search Bing via SerpAPI. Useful for cross-engine verification or when Google results are insufficient.

    Args:
        q: Search query string.
        cc: Country code (e.g. 'US', 'CN', 'GB').
        setlang: Language (e.g. 'en', 'zh-cn').
        count: Number of results (default 10).

    Returns:
        JSON string with search results.
    """
    if not SERPAPI_API_KEY:
        return "[ERROR]: SERPAPI_API_KEY is not set, serpapi_bing_search is unavailable."

    return await _call_serpapi_tool(
        "serpapi_bing_search",
        {"q": q, "cc": cc, "setlang": setlang, "count": count},
    )


@mcp.tool()
async def serpapi_baidu_search(
    q: str,
    rn: int = 10,
) -> str:
    """Search Baidu via SerpAPI. Best for Chinese-language queries and China-specific information.

    Args:
        q: Search query string (supports Chinese characters).
        rn: Number of results (default 10).

    Returns:
        JSON string with search results.
    """
    if not SERPAPI_API_KEY:
        return "[ERROR]: SERPAPI_API_KEY is not set, serpapi_baidu_search is unavailable."

    return await _call_serpapi_tool(
        "serpapi_baidu_search",
        {"q": q, "rn": rn},
    )


@mcp.tool()
async def serpapi_yahoo_search(
    p: str,
    n: int = 10,
) -> str:
    """Search Yahoo via SerpAPI.

    Args:
        p: Search query string.
        n: Number of results (default 10).

    Returns:
        JSON string with search results.
    """
    if not SERPAPI_API_KEY:
        return "[ERROR]: SERPAPI_API_KEY is not set, serpapi_yahoo_search is unavailable."

    return await _call_serpapi_tool(
        "serpapi_yahoo_search",
        {"p": p, "n": n},
    )


@mcp.tool()
async def serpapi_yandex_search(
    text: str,
    lang: str = "en",
) -> str:
    """Search Yandex via SerpAPI. Good for Russian-language and Eastern European content.

    Args:
        text: Search query string.
        lang: Language ('en', 'ru', etc.).

    Returns:
        JSON string with search results.
    """
    if not SERPAPI_API_KEY:
        return "[ERROR]: SERPAPI_API_KEY is not set, serpapi_yandex_search is unavailable."

    return await _call_serpapi_tool(
        "serpapi_yandex_search",
        {"text": text, "lang": lang},
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
