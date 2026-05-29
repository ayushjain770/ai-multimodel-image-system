"""Chat endpoint: orchestrated, moderated, grounded, remembered, verified.

Flow:
0. Input moderation (pre-LLM): block hateful/illegal/jailbreak requests with an
   on-brand refusal before anything else runs.
1. Rewrite/alter guard (pre-LLM): if the user asks to change a verse, refuse and
   return the authentic verse from the canonical store instead of fabricating.
2. Load memory (when session_id is set): summary of older turns + recent turns.
3. Classify intent (orchestrator): normal | scripture | image.
4. RAG retrieve only for scripture intent (and when enabled/populated).
5. Build a tone/denomination-aware system prompt and ground the LLM.
6. Output moderation: replace the reply if it contains unsafe content.
7. Verify (post-LLM) for scripture: check references against the canonical store.
8. Image intent (or generate_image): compose an art prompt, safety-check, render.
9. Persist the turn to memory (summarizing older turns past the threshold).

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
    IntentInfo,
    ModerationInfo,
    VerificationItem,
)
from app.services.image_prompt import check_safety, compose_image_prompt
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
    moderator = getattr(app.state, "moderator", None)
    orchestrator = getattr(app.state, "orchestrator", None)
    use_memory = memory is not None and payload.session_id is not None
    backend = BackendInfo(
        llm=settings.llm_backend.value, image=settings.image_backend.value
    )

    # 0. Input moderation: block hateful/illegal/jailbreak before the LLM.
    if moderator is not None:
        verdict = await moderator.moderate_input(payload.message)
        if not verdict.allowed:
            reply = verdict.message or settings.moderation_refusal
            if use_memory:
                await memory.append(payload.session_id, payload.message, reply)
            return ChatResponse(
                reply=reply,
                refused=True,
                moderated=True,
                moderation=ModerationInfo(
                    stage=verdict.stage,
                    category=verdict.category,
                    reason=verdict.reason,
                ),
                session_id=payload.session_id,
                backend=backend,
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

    # 3. Classify intent (decides RAG and image paths below).
    intent_info: IntentInfo | None = None
    if orchestrator is not None:
        intent = await orchestrator.classify(payload.message)
        intent_info = IntentInfo(
            kind=intent.kind,
            needs_rag=intent.needs_rag,
            tool=intent.tool,
            source=intent.source,
        )
        want_image = intent.kind == "image" or payload.generate_image
        want_rag = intent.needs_rag
    else:
        want_image = payload.generate_image
        want_rag = True

    # 4. RAG retrieve only when the intent needs grounding.
    citations: list[Citation] = []
    if (
        want_rag
        and settings.rag_enabled
        and await app.state.vector_client.collection_ready()
    ):
        citations = await app.state.retriever.retrieve(
            payload.message, payload.denomination
        )

    # 5. Build a tone/denomination-aware system prompt and ground the LLM.
    system_prompt = build_system_prompt(payload.denomination, summary)
    reply = await app.state.llm_client.chat(
        payload.message, history, citations, system_prompt=system_prompt
    )

    # 6. Output moderation: replace the reply if it slipped past with unsafe content.
    moderated = False
    moderation_info: ModerationInfo | None = None
    if moderator is not None:
        out = moderator.moderate_output(reply)
        if not out.allowed:
            reply = out.message or settings.moderation_refusal
            moderated = True
            moderation_info = ModerationInfo(
                stage=out.stage, category=out.category, reason=out.reason
            )

    # 7. Post-LLM verification: catch any hallucinated reference (skipped if moderated).
    verification: list[VerificationItem] = []
    if verifier is not None and not moderated:
        results = await verifier.verify_text(reply)
        verification = [VerificationItem(**vars(r)) for r in results]
        note = _correction_note(verification)
        if note:
            reply = reply + note

    # 8. Image intent: compose an art prompt (LLM-assisted), safety-check, render.
    image_b64: str | None = None
    if not moderated and want_image and check_safety(payload.message).ok:
        params = await compose_image_prompt(
            app.state.llm_client, payload.message, payload.denomination.value
        )
        image_b64 = await app.state.image_client.generate(params)

    # 9. Persist the turn (summarizes older turns past the threshold).
    if use_memory:
        await memory.append(payload.session_id, payload.message, reply)

    return ChatResponse(
        reply=reply,
        citations=citations,
        verification=verification,
        moderated=moderated,
        moderation=moderation_info,
        intent=intent_info,
        image_base64=image_b64,
        session_id=payload.session_id,
        backend=backend,
    )
