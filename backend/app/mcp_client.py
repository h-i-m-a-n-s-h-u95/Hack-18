"""
app/mcp_client.py — Utility to load tools from the TBuddy MCP server
using langchain-mcp-adapters.

Usage:
    from app.mcp_client import get_mcp_tools

    tools = await get_mcp_tools()          # returns LangChain-compatible tools
    llm_with_tools = llm.bind_tools(tools) # use in any agent
"""

import logging
from typing import List, Optional

from app.config.settings import settings

logger = logging.getLogger("mcp_client")


async def get_mcp_tools(
    server_url: Optional[str] = None,
) -> List:
    """
    Connect to the TBuddy MCP server via SSE and return LangChain-compatible
    tool objects that can be bound to any LLM.

    Args:
        server_url: Override MCP server URL (default: settings.mcp_server_url)

    Returns:
        List of LangChain-compatible tools loaded from the MCP server.
        Returns an empty list if the connection fails (caller should fall back
        to native tools).
    """
    url = server_url or settings.mcp_server_url

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client_config = {
            "tbuddy": {
                "transport": "sse",
                "url": url,
            }
        }

        client = MultiServerMCPClient(client_config)
        tools = await client.get_tools()
        logger.info(
            f"✅ Loaded {len(tools)} tools from MCP server at {url}"
        )
        return tools

    except ImportError:
        logger.error(
            "langchain-mcp-adapters is not installed. "
            "Run: pip install langchain-mcp-adapters"
        )
        return []
    except Exception as e:
        logger.warning(
            f"⚠️ Could not connect to MCP server at {url}: {e}. "
            "Falling back to native tools."
        )
        return []


async def check_mcp_health(server_url: Optional[str] = None) -> dict:
    """
    Quick health check — try to list tools from the MCP server.

    Returns:
        {"status": "healthy", "tool_count": N, "url": ...}
        or {"status": "unhealthy", "error": ..., "url": ...}
    """
    url = server_url or settings.mcp_server_url

    try:
        tools = await get_mcp_tools(url)
        if tools:
            return {
                "status": "healthy",
                "tool_count": len(tools),
                "url": url,
            }
        return {
            "status": "unhealthy",
            "error": "No tools returned",
            "url": url,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "url": url,
        }
