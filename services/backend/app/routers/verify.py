"""Standalone scripture verification endpoint.

Text in -> per-reference verification report out. Used for debugging, the MCP
`verse_verify` tool, and the future eval harness. Mirrors the post-LLM check the
chat endpoint runs on its own replies.
"""

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.schemas import VerificationItem, VerifyRequest, VerifyResponse

router = APIRouter(prefix="/api/v1", tags=["verify"])


@router.post("/verify", response_model=VerifyResponse)
async def verify(request: Request, payload: VerifyRequest) -> VerifyResponse:
    verifier = getattr(request.app.state, "verifier", None)
    if verifier is None:
        raise HTTPException(status_code=503, detail="Verification is disabled")

    results = await verifier.verify_text(payload.text)
    return VerifyResponse(
        text=payload.text,
        translation=settings.verify_translation,
        verification=[VerificationItem(**vars(r)) for r in results],
    )
