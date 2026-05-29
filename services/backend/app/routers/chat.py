"""Chat endpoints: orchestrated, moderated, grounded, remembered, verified.

Two endpoints share the same pipeline:
  - POST /api/v1/chat        -> one JSON ChatResponse (used by tests/MCP).
  - POST /api/v1/chat/stream -> Server-Sent Events (meta -> token* -> final -> done).

Pipeline:
0. Input moderation (pre-LLM): block hateful/illegal/jailbreak with a refusal.
1. Rewrite/alter guard (pre-LLM): refuse verse alteration; return the authentic verse.
2. Load memory (when session_id is set): rolling summary + last N turns.
3. Classify intent (orchestrator): normal | scripture | image.
4. RAG retrieve only for scripture intent (and when enabled/populated).
5. Build a tone/denomination-aware system prompt and ground the LLM.
6. Output moderation: replace the reply if it contains unsafe content.
7. Verify (post-LLM): check references against the canonical store.
8. Image intent (or generate_image): compose an art prompt, safety-check, render.
9. Persist the turn to memory (summarizing older turns past the threshold).

Steps 0-5 live in prepare_turn(); steps 6-8 in postprocess(). Works with the mock
LLM too, so the whole flow is demonstrable without a GPU.
"""

import json
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

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


@dataclass
class PreparedTurn:
    """Everything needed to call the LLM, computed by prepare_turn()."""

    history: list[ChatMessage]
    system_prompt: str
    citations: list[Citation]
    intent: IntentInfo | None
    want_image: bool
    use_memory: bool
    backend: BackendInfo


@dataclass
class Finalized:
    """Post-LLM result after output moderation, verification, and image."""

    reply: str
    moderated: bool
    moderation: ModerationInfo | None
    verification: list[VerificationItem]
    image_base64: str | None


def _trim_window(history: list[ChatMessage]) -> list[ChatMessage]:
    """Keep only the last context_recent_turns turns (one turn = 2 messages)."""
    keep = max(0, settings.context_recent_turns) * 2
    return history[-keep:] if keep else []


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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


async def prepare_turn(
    request: Request, payload: ChatRequest
) -> tuple[ChatResponse | None, PreparedTurn | None]:
    """Run steps 0-5. Return (early_response, None) for short-circuits
    (input moderation / rewrite guard), else (None, PreparedTurn)."""
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
            return (
                ChatResponse(
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
                ),
                None,
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
                return (
                    ChatResponse(
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
                    ),
                    None,
                )

    # 2. Load conversation memory, trimmed to the last N turns for the prompt.
    summary = ""
    if use_memory:
        summary, history = await memory.load(payload.session_id)
    else:
        history = payload.history
    history = _trim_window(history)

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

    # 5. Build a tone/denomination-aware system prompt.
    system_prompt = build_system_prompt(payload.denomination, summary)
    return None, PreparedTurn(
        history=history,
        system_prompt=system_prompt,
        citations=citations,
        intent=intent_info,
        want_image=want_image,
        use_memory=use_memory,
        backend=backend,
    )


async def postprocess(
    request: Request, payload: ChatRequest, prepared: PreparedTurn, reply: str
) -> Finalized:
    """Run steps 6-8 on a generated reply: output moderation, verify, image."""
    app = request.app
    verifier = getattr(app.state, "verifier", None)
    moderator = getattr(app.state, "moderator", None)

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

    verification: list[VerificationItem] = []
    if verifier is not None and not moderated:
        results = await verifier.verify_text(reply)
        verification = [VerificationItem(**vars(r)) for r in results]
        note = _correction_note(verification)
        if note:
            reply = reply + note

    image_b64: str | None = None
    if not moderated and prepared.want_image and check_safety(payload.message).ok:
        params = await compose_image_prompt(
            app.state.llm_client, payload.message, payload.denomination.value
        )
        image_b64 = await app.state.image_client.generate(params)

    return Finalized(
        reply=reply,
        moderated=moderated,
        moderation=moderation_info,
        verification=verification,
        image_base64=image_b64,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    early, prepared = await prepare_turn(request, payload)
    if early is not None:
        return early

    reply = await request.app.state.llm_client.chat(
        payload.message,
        prepared.history,
        prepared.citations,
        system_prompt=prepared.system_prompt,
    )
    fin = await postprocess(request, payload, prepared, reply)

    if prepared.use_memory:
        await request.app.state.memory.append(
            payload.session_id, payload.message, fin.reply
        )

    return ChatResponse(
        reply=fin.reply,
        citations=prepared.citations,
        verification=fin.verification,
        moderated=fin.moderated,
        moderation=fin.moderation,
        intent=prepared.intent,
        image_base64=fin.image_base64,
        session_id=payload.session_id,
        backend=prepared.backend,
    )


@router.post("/chat/stream")
async def chat_stream(request: Request, payload: ChatRequest) -> StreamingResponse:
    early, prepared = await prepare_turn(request, payload)

    async def gen():
        # Short-circuit (input moderation / rewrite guard): no LLM call.
        if early is not None:
            yield _sse(
                "meta",
                {
                    "intent": None,
                    "citations": [],
                    "session_id": early.session_id,
                    "backend": early.backend.model_dump(),
                },
            )
            yield _sse("token", {"delta": early.reply})
            yield _sse(
                "final",
                {
                    "reply": early.reply,
                    "refused": early.refused,
                    "moderated": early.moderated,
                    "moderation": early.moderation.model_dump()
                    if early.moderation
                    else None,
                    "verification": [v.model_dump() for v in early.verification],
                    "image_base64": None,
                },
            )
            yield _sse("done", {})
            return

        yield _sse(
            "meta",
            {
                "intent": prepared.intent.model_dump() if prepared.intent else None,
                "citations": [c.model_dump() for c in prepared.citations],
                "session_id": payload.session_id,
                "backend": prepared.backend.model_dump(),
            },
        )

        chunks: list[str] = []
        async for delta in request.app.state.llm_client.stream_chat(
            payload.message,
            prepared.history,
            prepared.citations,
            system_prompt=prepared.system_prompt,
        ):
            chunks.append(delta)
            yield _sse("token", {"delta": delta})

        fin = await postprocess(request, payload, prepared, "".join(chunks))

        if prepared.use_memory:
            await request.app.state.memory.append(
                payload.session_id, payload.message, fin.reply
            )

        yield _sse(
            "final",
            {
                "reply": fin.reply,
                "refused": False,
                "moderated": fin.moderated,
                "moderation": fin.moderation.model_dump() if fin.moderation else None,
                "verification": [v.model_dump() for v in fin.verification],
                "image_base64": fin.image_base64,
            },
        )
        yield _sse("done", {})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
