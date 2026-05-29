"""Chat endpoint with RAG grounding, conversation memory, and verification.

Flow:
1. Rewrite/alter guard (pre-LLM): if the user asks to change a verse, refuse and
   return the authentic verse from the canonical store instead of fabricating.
2. Load memory (when session_id is set): summary of older turns + recent turns.
3. RAG retrieve (when enabled and the collection is populated).
4. Build a tone/denomination-aware system prompt (with the memory summary) and
   ground the LLM with the retrieved verses.
5. Verify (post-LLM): check every scripture reference in the reply against the
   canonical store; attach a verification report and a correction note.
6. Persist the turn to memory (summarizing older turns past the threshold).

Works with the mock LLM too, so the whole flow is demonstrable without a GPU.
"""

from fastapi import APIRouter, Request

from app.core.config import settings
from app.schemas import (
    BackendInfo,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Citation,
    VerificationItem,
)
from app.services.image_prompt import build_prompt, check_safety
from app.services.prompt_builder import build_system_prompt

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
    memory = getattr(app.state, "memory", None)
    use_memory = memory is not None and payload.session_id is not None
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
                if use_memory:
                    await memory.append(payload.session_id, payload.message, reply)
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
                    session_id=payload.session_id,
                    backend=backend,
                )

    # 2. Load conversation memory (server-side when a session is supplied).
    summary = ""
    if use_memory:
        summary, history = await memory.load(payload.session_id)
    else:
        history: list[ChatMessage] = payload.history

    # 3. RAG retrieve.
    citations: list[Citation] = []
    if settings.rag_enabled and await app.state.vector_client.collection_ready():
        citations = await app.state.retriever.retrieve(
            payload.message, payload.denomination
        )

    # 4. Build a tone/denomination-aware system prompt and ground the LLM.
    system_prompt = build_system_prompt(payload.denomination, summary)
    reply = await app.state.llm_client.chat(
        payload.message, history, citations, system_prompt=system_prompt
    )

    # 5. Post-LLM verification.
    verification: list[VerificationItem] = []
    if verifier is not None:
        results = await verifier.verify_text(reply)
        verification = [VerificationItem(**vars(r)) for r in results]
        note = _correction_note(verification)
        if note:
            reply = reply + note

    image_b64: str | None = None
    if payload.generate_image and check_safety(payload.message).ok:
        # Seed the illustration with the strongest retrieved verse when present.
        scripture_context = citations[0].ref if citations else None
        params = build_prompt(payload.message, scripture_context=scripture_context)
        image_b64 = await app.state.image_client.generate(params)

    # 6. Persist the turn (summarizes older turns past the threshold).
    if use_memory:
        await memory.append(payload.session_id, payload.message, reply)

    return ChatResponse(
        reply=reply,
        citations=citations,
        verification=verification,
        image_base64=image_b64,
        session_id=payload.session_id,
        backend=backend,
    )
