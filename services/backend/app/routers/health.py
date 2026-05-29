"""Liveness and readiness endpoints."""

from fastapi import APIRouter, Request, Response, status

from app.schemas import DependencyStatus, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. No dependency checks."""
    return {"status": "ok"}


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(request: Request, response: Response) -> ReadinessResponse:
    """Readiness: probe the downstream dependencies we actually depend on."""
    app = request.app
    deps: list[DependencyStatus] = []

    for name, client in (
        ("llm", app.state.llm_client),
        ("image", app.state.image_client),
        ("qdrant", app.state.vector_client),
    ):
        ok, detail = await client.health()
        deps.append(DependencyStatus(name=name, ok=ok, detail=detail))

    overall_ok = all(d.ok for d in deps)
    if not overall_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ok" if overall_ok else "degraded", dependencies=deps
    )
