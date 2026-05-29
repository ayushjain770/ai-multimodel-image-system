"""Session memory inspection and reset.

Useful for demos and tests: see what the assistant remembers for a session, and
clear it. Returns 404 when memory is disabled or the session is unknown.
"""

from fastapi import APIRouter, HTTPException, Request

from app.schemas import SessionStateResponse

router = APIRouter(prefix="/api/v1", tags=["session"])


@router.get("/session/{session_id}", response_model=SessionStateResponse)
async def get_session(request: Request, session_id: str) -> SessionStateResponse:
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        raise HTTPException(status_code=404, detail="conversation memory is disabled")
    snap = await memory.snapshot(session_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionStateResponse(
        session_id=session_id,
        summary=snap.summary,
        recent=snap.recent,
        turns=len([m for m in snap.recent if m.role == "user"]),
    )


@router.delete("/session/{session_id}")
async def delete_session(request: Request, session_id: str) -> dict:
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        raise HTTPException(status_code=404, detail="conversation memory is disabled")
    cleared = await memory.reset(session_id)
    return {"session_id": session_id, "cleared": cleared}
