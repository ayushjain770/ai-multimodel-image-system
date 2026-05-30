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
    # Sampling temperature for chat completions (lower = steadier tone).
    llm_temperature: float = 0.4
    # Temperature for the image prompt composer LLM (scene rewrite before ComfyUI).
    image_composer_temperature: float = 0.3
    # Overridable persona/tone the system prompt is built around.
    llm_persona: str = (
        "You are a Christianity-focused assistant. You are pastoral, humble, and "
        "non-dogmatic, speaking with warmth and care."
    )

    # ComfyUI / image generation
    comfyui_base_url: str = "http://comfyui:8188"
    image_timeout: float = 300.0
    image_checkpoint: str = "juggernautXL.safetensors"
    image_steps: int = 30
    image_cfg: float = 6.5
    image_width: int = 1024
    image_height: int = 1024
    image_sampler: str = "dpmpp_2m"
    image_scheduler: str = "karras"
    # Style wrapper applied to every prompt ({theme} is substituted).
    image_style_template: str = (
        "reverent Christian fine-art illustration of {theme}, sacred, dignified, "
        "soft natural light, painterly, highly detailed, tasteful composition"
    )
    image_negative_prompt: str = (
        "lowres, blurry, watermark, signature, text, deformed, extra limbs, "
        "nsfw, gore, hateful, offensive, mocking, blasphemous"
    )
    image_safety_enabled: bool = True

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

    # Orchestrator / planner (intent routing)
    orchestrator_enabled: bool = True
    # Deprecated: vLLM planner runs automatically when LLM_BACKEND=vllm.
    orchestrator_llm_intent: bool = False
    planner_instruction: str = (
        "You are the routing planner for a Christianity-focused assistant. "
        "Classify the user message into exactly one route:\n"
        "- normal: general chat, greetings, or topics NOT related to Christianity "
        "(weather, sports, coding, etc.)\n"
        "- scripture: questions about the Bible, Jesus, faith, prayer, church, "
        "Christian doctrine, or Scripture\n"
        "- image: user wants to create, draw, paint, or generate a picture/photo\n"
        "Reply with ONLY valid JSON: {\"route\":\"normal|scripture|image\","
        "\"reason\":\"brief explanation\"}"
    )
    # Minimum Qdrant similarity score to accept a RAG hit (0-1).
    rag_min_score: float = 0.35
    rag_miss_reply: str = (
        "I couldn't find enough grounded Scripture in my corpus to answer that "
        "confidently. I'd rather not guess — could you rephrase or ask about a "
        "specific passage?"
    )
    # System prompt for the image prompt-composer (turns a request into a scene).
    image_composer_instruction: str = (
        "You are an art director for reverent Christian fine art. Rewrite the "
        "user's request into a single vivid, tasteful scene description suitable "
        "for an image model. Keep it concrete and dignified, avoid text/words in "
        "the image, and never depict anything explicit, violent, or mocking. "
        "Reply with only the scene description, one sentence."
    )

    # Safety / moderation
    moderation_enabled: bool = True
    # Optional Qwen-as-judge second opinion on borderline input (prod opt-in).
    moderation_llm_judge: bool = False
    # On-brand refusal returned when a request is blocked.
    moderation_refusal: str = (
        "I'm sorry, but I can't help with that. I'm here to support you with "
        "Scripture, faith, and Christian life in a respectful way. If there's "
        "something along those lines I can help with, I'd be glad to."
    )

    # Conversation memory (server-side, keyed by session_id)
    memory_enabled: bool = True
    # Recent turns kept verbatim in the prompt (one turn = user + assistant).
    memory_max_turns: int = 8
    # When stored turns exceed this, the oldest are folded into a running summary
    # so prompts stay bounded across long conversations.
    memory_summary_threshold: int = 12
    # Recent turns actually sent to the model per request (rolling summary covers
    # the rest). Smaller than memory_max_turns so storage can stay richer for the
    # session view while the prompt window remains "summary + last N turns".
    context_recent_turns: int = 3

    # Durable chat store (Postgres). When disabled, falls back to in-process memory.
    chat_store_enabled: bool = True
    database_url: str = "postgresql+asyncpg://christai:christai@postgres:5432/christai"
    # Where rendered PNGs are written and the URL path they are served under.
    media_dir: str = "/data/media"
    media_url_path: str = "/media"


settings = Settings()
