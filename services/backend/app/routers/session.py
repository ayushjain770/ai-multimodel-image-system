"""Session memory inspection and reset.

Useful for demos and tests: see what the assistant remembers for a session, and
clear it. Returns 404 when memory is disabled or the session is unknown.
"""

from fastapi import APIRouter, HTTPException, Request

from app.schemas import (
    HistoryResponse,
    HistoryTurn,
    SessionListResponse,
    SessionStateResponse,
    SessionSummary,
)

router = APIRouter(prefix="/api/v1", tags=["session"])


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(request: Request) -> SessionListResponse:
    store = getattr(request.app.state, "chat_store", None)
    if store is None:
        raise HTTPException(status_code=404, detail="durable chat store is disabled")
    rows = await store.list_sessions()
    return SessionListResponse(sessions=[SessionSummary(**r) for r in rows])


@router.get("/session/{session_id}/history", response_model=HistoryResponse)
async def get_history(request: Request, session_id: str) -> HistoryResponse:
    store = getattr(request.app.state, "chat_store", None)
    if store is None:
        raise HTTPException(status_code=404, detail="durable chat store is disabled")
    history = await store.get_history(session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="session not found")
    return HistoryResponse(
        session_id=session_id, turns=[HistoryTurn(**t) for t in history]
    )


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
