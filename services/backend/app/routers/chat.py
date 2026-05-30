"""Chat endpoints: Planner → Execute → Synthesizer pipeline with SSE streaming.

Two endpoints share the same pipeline:
  - POST /api/v1/chat        -> one JSON ChatResponse.
  - POST /api/v1/chat/stream -> Server-Sent Events (meta -> token* -> final -> done).

Pipeline:
0. Input moderation (pre-LLM).
1. Rewrite/alter guard (pre-LLM).
2. Load memory (summary + last N turns).
3. Planner: normal | scripture | image.
4. Execute: RAG (scripture) or image compose (image / generate_image flag).
5. rag_miss short-circuit (honest template, no synthesizer).
6. Synthesizer LLM (stream or single reply).
7. postprocess: render pre-composed image, output moderation, verify, persist.
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
from app.services.image_prompt import ImageParams, check_safety, compose_image_prompt
from app.services.planner import Plan
from app.services.prompt_builder import build_synthesizer_prompt

router = APIRouter(prefix="/api/v1", tags=["chat"])


@dataclass
class PreparedTurn:
    """Everything needed for the synthesizer LLM after planner + execution."""

    history: list[ChatMessage]
    system_prompt: str
    citations: list[Citation]
    intent: IntentInfo | None
    plan: Plan | None
    rag_miss: bool
    image_params: ImageParams | None
    backend: BackendInfo


@dataclass
class Finalized:
    """Post-synthesizer result after moderation, verification, and image render."""

    reply: str
    moderated: bool
    moderation: ModerationInfo | None
    verification: list[VerificationItem]
    image_base64: str | None
    image_url: str | None = None
    image_id: str | None = None


def _trim_window(history: list[ChatMessage]) -> list[ChatMessage]:
    keep = max(0, settings.context_recent_turns) * 2
    return history[-keep:] if keep else []


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _plan_to_intent(plan: Plan, rag_miss: bool = False) -> IntentInfo:
    return IntentInfo(
        kind=plan.route,
        needs_rag=plan.needs_rag,
        tool=plan.tool,
        source=plan.source,
        reason=plan.reason,
        rag_miss=rag_miss if plan.route == "scripture" else None,
    )


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


def _rag_miss_response(
    payload: ChatRequest, plan: Plan, backend: BackendInfo
) -> ChatResponse:
    return ChatResponse(
        reply=settings.rag_miss_reply,
        intent=_plan_to_intent(plan, rag_miss=True),
        session_id=payload.session_id,
        backend=backend,
    )


async def persist_turn(
    request: Request,
    payload: ChatRequest,
    reply: str,
    intent_kind: str | None = None,
    image_id: str | None = None,
) -> None:
    if payload.session_id is None:
        return
    app = request.app
    chat_store = getattr(app.state, "chat_store", None)
    if chat_store is not None:
        await chat_store.record_turn(
            payload.session_id,
            payload.denomination.value,
            payload.message,
            reply,
            intent_kind,
            image_id,
        )
        return
    memory = getattr(app.state, "memory", None)
    if memory is not None:
        await memory.append(payload.session_id, payload.message, reply)


async def prepare_turn(
    request: Request, payload: ChatRequest
) -> tuple[ChatResponse | None, PreparedTurn | None]:
    """Planner + execution. Returns early ChatResponse or PreparedTurn for synthesizer."""
    app = request.app
    verifier = getattr(app.state, "verifier", None)
    memory = getattr(app.state, "memory", None)
    moderator = getattr(app.state, "moderator", None)
    planner = getattr(app.state, "planner", None)
    use_memory = memory is not None and payload.session_id is not None
    backend = BackendInfo(
        llm=settings.llm_backend.value, image=settings.image_backend.value
    )

    if moderator is not None:
        verdict = await moderator.moderate_input(payload.message)
        if not verdict.allowed:
            reply = verdict.message or settings.moderation_refusal
            await persist_turn(request, payload, reply)
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
                await persist_turn(request, payload, reply)
                return (
                    ChatResponse(
                        reply=reply,
                        verification=[
                            VerificationItem(
                                ref=ref,
                                status="valid",
                                book=target.book,
                                chapter=target.chapter,
                                verse=target.verse,
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

    summary = ""
    if use_memory:
        summary, history = await memory.load(payload.session_id)
    else:
        history = payload.history
    history = _trim_window(history)

    # Planner
    if planner is not None:
        plan = await planner.plan(payload.message)
    else:
        from app.services.planner import classify_rules

        plan = classify_rules(payload.message)

    want_image = plan.route == "image" or payload.generate_image
    want_rag = plan.needs_rag

    # Execute: RAG for scripture route
    citations: list[Citation] = []
    rag_miss = False
    if want_rag and settings.rag_enabled and app.state.retriever is not None:
        collection_ready = await app.state.vector_client.collection_ready()
        if collection_ready:
            citations = await app.state.retriever.retrieve(
                payload.message, payload.denomination
            )
            rag_miss = len(citations) == 0
        else:
            rag_miss = True

    if plan.route == "scripture" and rag_miss:
        reply = settings.rag_miss_reply
        await persist_turn(request, payload, reply, plan.route)
        return (_rag_miss_response(payload, plan, backend), None)

    # Execute: image compose (execution-phase LLM call)
    image_params: ImageParams | None = None
    if want_image:
        safety = check_safety(payload.message)
        if not safety.ok:
            reply = safety.reason or settings.moderation_refusal
            await persist_turn(request, payload, reply, plan.route)
            return (
                ChatResponse(
                    reply=reply,
                    refused=True,
                    intent=_plan_to_intent(plan),
                    session_id=payload.session_id,
                    backend=backend,
                ),
                None,
            )
        image_params = await compose_image_prompt(
            app.state.llm_client, payload.message, payload.denomination.value
        )

    intent_info = _plan_to_intent(plan, rag_miss=False)
    synth_plan = plan
    if want_image and plan.route != "image":
        synth_plan = Plan(
            route="image",
            tool="generate_image",
            reason=plan.reason,
            source=plan.source,
            needs_rag=False,
        )
    system_prompt = build_synthesizer_prompt(synth_plan, payload.denomination, summary)

    return None, PreparedTurn(
        history=history,
        system_prompt=system_prompt,
        citations=citations,
        intent=intent_info,
        plan=plan,
        rag_miss=False,
        image_params=image_params,
        backend=backend,
    )


async def postprocess(
    request: Request, payload: ChatRequest, prepared: PreparedTurn, reply: str
) -> Finalized:
    """Output moderation, verify (scripture route), render pre-composed image."""
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
    scripture_route = prepared.plan is not None and prepared.plan.route == "scripture"
    if verifier is not None and not moderated and scripture_route:
        results = await verifier.verify_text(reply)
        verification = [VerificationItem(**vars(r)) for r in results]
        note = _correction_note(verification)
        if note:
            reply = reply + note

    image_b64: str | None = None
    image_url: str | None = None
    image_id: str | None = None
    if not moderated and prepared.image_params is not None:
        rendered = await app.state.image_client.generate(prepared.image_params)
        chat_store = getattr(app.state, "chat_store", None)
        if chat_store is not None and payload.session_id is not None:
            ref = await chat_store.save_image(
                payload.session_id,
                rendered,
                prepared.image_params.positive,
                prepared.image_params.negative,
            )
            image_url = ref.url
            image_id = ref.id
        else:
            image_b64 = rendered

    return Finalized(
        reply=reply,
        moderated=moderated,
        moderation=moderation_info,
        verification=verification,
        image_base64=image_b64,
        image_url=image_url,
        image_id=image_id,
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

    await persist_turn(
        request,
        payload,
        fin.reply,
        prepared.intent.kind if prepared.intent else None,
        fin.image_id,
    )

    return ChatResponse(
        reply=fin.reply,
        citations=prepared.citations,
        verification=fin.verification,
        moderated=fin.moderated,
        moderation=fin.moderation,
        intent=prepared.intent,
        image_base64=fin.image_base64,
        image_url=fin.image_url,
        session_id=payload.session_id,
        backend=prepared.backend,
    )


@router.post("/chat/stream")
async def chat_stream(request: Request, payload: ChatRequest) -> StreamingResponse:
    early, prepared = await prepare_turn(request, payload)

    async def gen():
        if early is not None:
            yield _sse(
                "meta",
                {
                    "intent": early.intent.model_dump() if early.intent else None,
                    "citations": [c.model_dump() for c in early.citations],
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
                    "image_url": None,
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

        await persist_turn(
            request,
            payload,
            fin.reply,
            prepared.intent.kind if prepared.intent else None,
            fin.image_id,
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
                "image_url": fin.image_url,
            },
        )
        yield _sse("done", {})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
