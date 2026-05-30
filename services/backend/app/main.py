"""FastAPI gateway entrypoint."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.clients.comfy_client import build_image_client
from app.clients.embeddings import build_embedding_client
from app.clients.llm_client import build_llm_client
from app.clients.qdrant_client import build_vector_client
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db import engine as db_engine
from app.routers import (
    chat,
    compose,
    health,
    image,
    moderate,
    search,
    session,
    verify,
)
from app.services.chat_store import build_chat_store
from app.services.memory import build_memory
from app.services.moderation import build_moderator
from app.services.planner import build_planner
from app.services.retriever import Retriever
from app.services.verifier import build_verifier

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info(
        "Starting gateway (env=%s, llm=%s, image=%s)",
        settings.app_env,
        settings.llm_backend.value,
        settings.image_backend.value,
    )
    app.state.llm_client = build_llm_client()
    app.state.image_client = build_image_client()
    app.state.vector_client = build_vector_client()
    if settings.rag_enabled:
        app.state.embedding_client = build_embedding_client()
        app.state.retriever = Retriever(
            app.state.embedding_client, app.state.vector_client
        )
    else:
        app.state.retriever = None
        logger.info("RAG disabled (RAG_ENABLED=false)")
    if settings.verify_enabled:
        app.state.verifier = build_verifier(app.state.vector_client)
    else:
        app.state.verifier = None
        logger.info("Verification disabled (VERIFY_ENABLED=false)")
    app.state.chat_store = None
    if settings.chat_store_enabled:
        try:
            await db_engine.init_models()
            app.state.chat_store = build_chat_store(
                db_engine.get_sessionmaker(), app.state.llm_client.summarize
            )
            app.state.memory = app.state.chat_store
        except Exception as exc:
            logger.warning(
                "Chat store init failed (%s); falling back to in-memory", exc
            )
            app.state.chat_store = None
    if app.state.chat_store is None:
        if settings.memory_enabled:
            app.state.memory = build_memory(app.state.llm_client.summarize)
        else:
            app.state.memory = None
            logger.info("Conversation memory disabled (MEMORY_ENABLED=false)")
    if settings.moderation_enabled:
        app.state.moderator = build_moderator(app.state.llm_client)
    else:
        app.state.moderator = None
        logger.info("Moderation disabled (MODERATION_ENABLED=false)")
    app.state.planner = (
        build_planner(app.state.llm_client)
        if settings.orchestrator_enabled
        else None
    )
    try:
        yield
    finally:
        await app.state.llm_client.aclose()
        await app.state.image_client.aclose()
        await app.state.vector_client.aclose()
        await db_engine.dispose()
        logger.info("Gateway shut down cleanly")


app = FastAPI(title="Christianity AI Assistant - Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in a later phase
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve rendered images from the media volume.
os.makedirs(settings.media_dir, exist_ok=True)
app.mount(
    settings.media_url_path,
    StaticFiles(directory=settings.media_dir),
    name="media",
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(search.router)
app.include_router(verify.router)
app.include_router(image.router)
app.include_router(session.router)
app.include_router(moderate.router)
app.include_router(compose.router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"service": "gateway", "status": "ok"}
