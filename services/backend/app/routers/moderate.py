"""Standalone moderation endpoint.

Screens arbitrary text with the same rule layer the chat flow uses. `stage`
selects the input-side rules (jailbreak/self-harm included) or the narrower
output-side rules. Returns 404 when moderation is disabled.
"""

from fastapi import APIRouter, HTTPException, Request

from app.schemas import ModerateRequest, ModerateResponse

router = APIRouter(prefix="/api/v1", tags=["moderate"])


@router.post("/moderate", response_model=ModerateResponse)
async def moderate(request: Request, payload: ModerateRequest) -> ModerateResponse:
    moderator = getattr(request.app.state, "moderator", None)
    if moderator is None:
        raise HTTPException(status_code=404, detail="moderation is disabled")
    if payload.stage == "output":
        result = moderator.moderate_output(payload.text)
    else:
        result = await moderator.moderate_input(payload.text)
    return ModerateResponse(
        allowed=result.allowed,
        stage=result.stage,
        category=result.category,
        reason=result.reason,
    )
