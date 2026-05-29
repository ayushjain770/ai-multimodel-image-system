"""FastMCP server.

Tools:
  - ping            : health/liveness.
  - scripture_search: grounded Bible verse retrieval, delegated to the backend
                      gateway's /api/v1/search (URL from env, no hardcoding).
  - verse_verify    : anti-hallucination check of scripture references in text,
                      delegated to the backend gateway's /api/v1/verify.
  - generate_image  : Christian-themed image generation, delegated to the
                      backend gateway's /api/v1/image.
  - moderate        : safety/moderation screening of text, delegated to the
                      backend gateway's /api/v1/moderate.
  - prompt_composer : LLM-assisted Christian image prompt, delegated to the
                      backend gateway's /api/v1/compose_image_prompt.
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
        "phase": 3,
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


@mcp.tool
def verse_verify(text: str) -> dict:
    """Verify scripture references in text against the canonical Bible store.

    Flags fabricated or misquoted verses so model output can be trusted.

    Args:
        text: Any text that may contain scripture references (and quoted verses).

    Returns a per-reference report with status valid | unknown_book |
    nonexistent | misquote, plus the authentic canonical text when available.
    """
    resp = httpx.post(
        f"{BACKEND_URL}/api/v1/verify",
        json={"text": text},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


@mcp.tool
def generate_image(prompt: str, denomination: str = "neutral") -> dict:
    """Generate a reverent Christian-themed image for a prompt.

    The backend applies safe style templating and refuses disallowed imagery.

    Args:
        prompt: Theme or subject to illustrate.
        denomination: neutral | catholic | protestant | orthodox.

    Returns the base64 PNG (image_base64), the prompt actually used, and whether
    the request was refused.
    """
    resp = httpx.post(
        f"{BACKEND_URL}/api/v1/image",
        json={"prompt": prompt, "denomination": denomination},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


@mcp.tool
def prompt_composer(request: str, denomination: str = "neutral") -> dict:
    """Compose a structured, reverent Christian image prompt from a raw request.

    Returns the positive/negative SDXL prompt without rendering, so it can be
    chained into generate_image. Refuses disallowed requests.

    Args:
        request: The raw image idea (e.g. "the empty tomb at sunrise").
        denomination: neutral | catholic | protestant | orthodox.
    """
    resp = httpx.post(
        f"{BACKEND_URL}/api/v1/compose_image_prompt",
        json={"request": request, "denomination": denomination},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


@mcp.tool
def moderate(text: str, stage: str = "input") -> dict:
    """Screen text with the assistant's safety/moderation rules.

    Args:
        text: The content to screen.
        stage: input (jailbreak/self-harm included) or output (narrower rules).

    Returns whether the text is allowed plus the matched category and reason.
    """
    resp = httpx.post(
        f"{BACKEND_URL}/api/v1/moderate",
        json={"text": text, "stage": stage},
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
