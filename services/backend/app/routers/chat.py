"""Chat endpoint with RAG grounding.

Flow: retrieve scripture (when RAG is enabled and the collection is populated)
-> ground the LLM with the retrieved verses -> return reply + citations. Works
with the mock LLM too, so grounding is demonstrable without a GPU.
"""

from fastapi import APIRouter, Request

from app.core.config import settings
from app.schemas import BackendInfo, ChatRequest, ChatResponse, Citation

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    app = request.app

    citations: list[Citation] = []
    if settings.rag_enabled and await app.state.vector_client.collection_ready():
        citations = await app.state.retriever.retrieve(
            payload.message, payload.denomination
        )

    reply = await app.state.llm_client.chat(
        payload.message, payload.history, citations
    )

    image_b64: str | None = None
    if payload.generate_image:
        image_b64 = await app.state.image_client.generate(payload.message)

    return ChatResponse(
        reply=reply,
        citations=citations,
        image_base64=image_b64,
        backend=BackendInfo(
            llm=settings.llm_backend.value, image=settings.image_backend.value
        ),
    )
