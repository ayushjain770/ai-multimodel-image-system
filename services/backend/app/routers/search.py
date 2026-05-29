"""Scripture search endpoint - thin wrapper over the retriever.

Used by the MCP `scripture_search` tool and for debugging grounding directly.
"""

from fastapi import APIRouter, Request

from app.schemas import SearchRequest, SearchResponse

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(request: Request, payload: SearchRequest) -> SearchResponse:
    citations = await request.app.state.retriever.retrieve(
        payload.query, payload.denomination, payload.top_k
    )
    return SearchResponse(
        query=payload.query,
        denomination=payload.denomination,
        citations=citations,
    )
