"""FastAPI gateway entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients.comfy_client import build_image_client
from app.clients.embeddings import build_embedding_client
from app.clients.llm_client import build_llm_client
from app.clients.qdrant_client import build_vector_client
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.routers import chat, health, search
from app.services.retriever import Retriever

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
    try:
        yield
    finally:
        await app.state.llm_client.aclose()
        await app.state.image_client.aclose()
        await app.state.vector_client.aclose()
        logger.info("Gateway shut down cleanly")


app = FastAPI(title="Christianity AI Assistant - Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in a later phase
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(search.router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"service": "gateway", "status": "ok"}
