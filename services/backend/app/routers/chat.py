"""Chat round-trip endpoint (Phase 1 stub).

Proves the full path UI -> gateway -> LLM (+ optional image). Grounding,
citations, memory, and safety are added in later phases.
"""

from fastapi import APIRouter, Request

from app.core.config import settings
from app.schemas import BackendInfo, ChatRequest, ChatResponse

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    app = request.app

    reply = await app.state.llm_client.chat(payload.message, payload.history)

    image_b64: str | None = None
    if payload.generate_image:
        image_b64 = await app.state.image_client.generate(payload.message)

    return ChatResponse(
        reply=reply,
        image_base64=image_b64,
        backend=BackendInfo(
            llm=settings.llm_backend.value, image=settings.image_backend.value
        ),
    )
