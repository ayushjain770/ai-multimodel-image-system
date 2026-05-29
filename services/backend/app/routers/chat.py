"""Chat endpoint with RAG grounding and scripture verification.

Flow:
1. Rewrite/alter guard (pre-LLM): if the user asks to change a verse, refuse and
   return the authentic verse from the canonical store instead of fabricating.
2. RAG retrieve (when enabled and the collection is populated).
3. Ground the LLM with the retrieved verses.
4. Verify (post-LLM): check every scripture reference in the reply against the
   canonical store; attach a verification report and a correction note for any
   fabricated or misquoted reference.

Works with the mock LLM too, so the whole flow is demonstrable without a GPU.
"""

from fastapi import APIRouter, Request

from app.core.config import settings
from app.schemas import (
    BackendInfo,
    ChatRequest,
    ChatResponse,
    Citation,
    VerificationItem,
)

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _correction_note(items: list[VerificationItem]) -> str | None:
    problems = [i for i in items if i.status != "valid"]
    if not problems:
        return None
    lines = ["", "", "Note on scripture accuracy:"]
    for p in problems:
        if p.status == "misquote" and p.canonical_text:
            lines.append(f"- {p.ref} actually reads: \u201c{p.canonical_text}\u201d")
        elif p.status == "nonexistent":
            lines.append(f"- {p.ref} is not a valid reference and was not asserted.")
        elif p.status == "unknown_book":
            lines.append(f"- {p.ref} does not name a canonical book.")
    return "\n".join(lines)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    app = request.app
    verifier = getattr(app.state, "verifier", None)
    backend = BackendInfo(
        llm=settings.llm_backend.value, image=settings.image_backend.value
    )

    # 1. Pre-LLM rewrite/alter guard.
    if verifier is not None:
        target = verifier.detect_rewrite_intent(payload.message)
        if target is not None:
            authentic = await verifier.authentic_verse(target)
            if authentic is not None:
                ref = f"{target.book} {target.chapter}:{target.verse}"
                reply = (
                    "I can't rewrite or alter the words of Scripture. Here is the "
                    f"authentic text of {ref} ({settings.verify_translation}):\n\n"
                    f"\u201c{authentic}\u201d\n\n"
                    "I'm happy to explain its meaning, context, or how it applies."
                )
                return ChatResponse(
                    reply=reply,
                    verification=[
                        VerificationItem(
                            ref=ref, status="valid", book=target.book,
                            chapter=target.chapter, verse=target.verse,
                            canonical_text=authentic,
                            message="Returned the authentic verse; alteration refused.",
                        )
                    ],
                    refused=True,
                    backend=backend,
                )

    # 2. RAG retrieve.
    citations: list[Citation] = []
    if settings.rag_enabled and await app.state.vector_client.collection_ready():
        citations = await app.state.retriever.retrieve(
            payload.message, payload.denomination
        )

    # 3. Ground the LLM.
    reply = await app.state.llm_client.chat(payload.message, payload.history, citations)

    # 4. Post-LLM verification.
    verification: list[VerificationItem] = []
    if verifier is not None:
        results = await verifier.verify_text(reply)
        verification = [VerificationItem(**vars(r)) for r in results]
        note = _correction_note(verification)
        if note:
            reply = reply + note

    image_b64: str | None = None
    if payload.generate_image:
        image_b64 = await app.state.image_client.generate(payload.message)

    return ChatResponse(
        reply=reply,
        citations=citations,
        verification=verification,
        image_base64=image_b64,
        backend=backend,
    )
