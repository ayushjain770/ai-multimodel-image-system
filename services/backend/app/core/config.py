"""Environment-driven application configuration."""

from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMBackend(str, Enum):
    MOCK = "mock"
    VLLM = "vllm"


class ImageBackend(str, Enum):
    MOCK = "mock"
    COMFY = "comfy"


class Settings(BaseSettings):
    """All runtime configuration. Values come from env vars (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"

    # Backend selection
    llm_backend: LLMBackend = LLMBackend.MOCK
    image_backend: ImageBackend = ImageBackend.MOCK

    # vLLM (OpenAI-compatible)
    vllm_base_url: str = "http://vllm:8000/v1"
    vllm_model: str = "Qwen/Qwen2.5-VL-3B-Instruct"
    llm_timeout: float = 120.0

    # ComfyUI
    comfyui_base_url: str = "http://comfyui:8188"
    image_timeout: float = 300.0

    # Qdrant
    qdrant_url: str = "http://qdrant:6333"

    # MCP server
    mcp_server_url: str = "http://mcp-server:8001/mcp"

    # RAG / Bible grounding
    rag_enabled: bool = True
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # Instruction prefix applied to queries (bge-style retrieval models expect
    # one for the query side only). Set blank for models that don't need it.
    embedding_query_prefix: str = (
        "Represent this sentence for searching relevant passages: "
    )
    qdrant_collection: str = "bible_verses"
    rag_top_k: int = 5

    # Anti-hallucination / verse verification
    verify_enabled: bool = True
    # Translation whose canonical text references are validated against.
    verify_translation: str = "KJV"
    # difflib ratio below which a quoted verse is treated as a misquote.
    verify_fuzzy_threshold: float = 0.6


settings = Settings()
