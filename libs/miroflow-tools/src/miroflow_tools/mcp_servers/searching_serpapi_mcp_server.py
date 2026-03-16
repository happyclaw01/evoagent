# Copyright (c) 2025 MiroMind
# This source code is licensed under the MIT License.

"""
High-level SerpAPI Baidu search tool exposed as FastMCP server.
Google/Bing search is handled by Serper.dev (searching_google_mcp_server.py).
"""

import asyncio
import os
import sys

from fastmcp import FastMCP
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

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
                async with ClientSession(
                    read, write, sampling_callback=None
                ) as session:
                    await session.initialize()
                    tool_result = await session.call_tool(
                        tool_name, arguments=arguments
                    )
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
async def baidu_search(
    q: str,
    rn: int = 10,
    pn: int = 0,
) -> str:
    """Search Baidu via SerpAPI. Best for Chinese-language queries and China-specific information.
    Use this tool when:
    - The query is in Chinese
    - Searching for China-specific information (companies, events, regulations, celebrities)
    - Google results lack Chinese-language sources
    - Cross-verifying information with a Chinese search engine

    For English/international queries, prefer google_search (Serper.dev) instead.

    Args:
        q: Search query string (supports Chinese characters).
        rn: Number of results per page (default 10, max 50).
        pn: Result offset for pagination (default 0; use 10 for page 2, 20 for page 3).

    Returns:
        JSON string with search results including organic listings.
    """
    if not SERPAPI_API_KEY:
        return "[ERROR]: SERPAPI_API_KEY is not set, baidu_search is unavailable."

    return await _call_serpapi_tool(
        "baidu_search",
        {"q": q, "rn": rn, "pn": pn},
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
