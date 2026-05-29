"""FastMCP server (Phase 1 skeleton).

Exposes a single `ping` tool over the streamable-http transport on :8001.
Scripture-search, verse-verify, and image-generation tools land in later
phases; this just proves the MCP surface is wired and reachable.
"""

import os
from datetime import datetime, timezone

from fastmcp import FastMCP

mcp = FastMCP("christ-ai-tools")


@mcp.tool
def ping() -> dict:
    """Health/liveness check. Returns server identity and current UTC time."""
    return {
        "status": "ok",
        "server": "christ-ai-tools",
        "phase": 1,
        "time": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("MCP_PORT", "8001")),
    )
