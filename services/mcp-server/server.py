"""FastMCP server.

Tools:
  - ping            : health/liveness.
  - scripture_search: grounded Bible verse retrieval, delegated to the backend
                      gateway's /api/v1/search (URL from env, no hardcoding).
"""

import os
from datetime import datetime, timezone

import httpx
from fastmcp import FastMCP

mcp = FastMCP("christ-ai-tools")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8080").rstrip("/")
HTTP_TIMEOUT = float(os.environ.get("MCP_HTTP_TIMEOUT", "30"))


@mcp.tool
def ping() -> dict:
    """Health/liveness check. Returns server identity and current UTC time."""
    return {
        "status": "ok",
        "server": "christ-ai-tools",
        "phase": 2,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@mcp.tool
def scripture_search(
    query: str, denomination: str = "neutral", top_k: int = 5
) -> dict:
    """Retrieve grounded Bible verses for a query.

    Args:
        query: Natural-language question or topic.
        denomination: neutral | catholic | protestant | orthodox (filters canon).
        top_k: Maximum number of verses to return.
    """
    resp = httpx.post(
        f"{BACKEND_URL}/api/v1/search",
        json={"query": query, "denomination": denomination, "top_k": top_k},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("MCP_PORT", "8001")),
    )
