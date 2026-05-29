"""Image prompt-composer endpoint.

Turns a raw user request into a structured, style-wrapped SDXL prompt using the
LLM (mock or vLLM) without rendering. Lets the orchestrator / MCP agent chain
compose -> render, and refuses disallowed requests up front.
"""

from fastapi import APIRouter, Request

from app.core.config import settings
from app.schemas import ComposeRequest, ComposeResponse
from app.services.image_prompt import check_safety, compose_image_prompt

router = APIRouter(prefix="/api/v1", tags=["compose"])


@router.post("/compose_image_prompt", response_model=ComposeResponse)
async def compose(request: Request, payload: ComposeRequest) -> ComposeResponse:
    backend = settings.image_backend.value

    safety = check_safety(payload.request)
    if not safety.ok:
        return ComposeResponse(refused=True, reason=safety.reason, backend=backend)

    params = await compose_image_prompt(
        request.app.state.llm_client,
        payload.request,
        payload.denomination.value,
        negative_override=payload.negative,
    )
    return ComposeResponse(
        positive=params.positive,
        negative=params.negative,
        backend=backend,
    )
