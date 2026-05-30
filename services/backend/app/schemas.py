"""Request/response models for the gateway API."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Denomination(str, Enum):
    NEUTRAL = "neutral"
    CATHOLIC = "catholic"
    PROTESTANT = "protestant"
    ORTHODOX = "orthodox"


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Latest user message")
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="Prior turns (used only when session_id is absent)",
    )
    session_id: str | None = Field(
        default=None,
        description="Opaque conversation id; when set, server-side memory is used",
    )
    denomination: Denomination = Field(
        default=Denomination.NEUTRAL,
        description="Filters canon for grounding and frames disputed doctrine",
    )
    generate_image: bool = Field(
        default=False, description="Also generate a themed image for this turn"
    )


class Citation(BaseModel):
    ref: str
    translation: str
    book: str
    chapter: int
    verse: int
    text: str
    score: float


class BackendInfo(BaseModel):
    llm: str
    image: str


class ModerationInfo(BaseModel):
    stage: Literal["input", "output"]
    category: str | None = None
    reason: str | None = None


class IntentInfo(BaseModel):
    kind: Literal["normal", "scripture", "image"]
    needs_rag: bool
    tool: str | None = None
    source: str
    reason: str | None = None
    rag_miss: bool | None = None


VerificationStatus = Literal["valid", "unknown_book", "nonexistent", "misquote"]


class VerificationItem(BaseModel):
    ref: str
    status: VerificationStatus
    book: str | None = None
    chapter: int | None = None
    verse: int | None = None
    canonical_text: str | None = None
    quoted_text: str | None = None
    similarity: float | None = None
    message: str


class ChatResponse(BaseModel):
    reply: str
    citations: list[Citation] = Field(default_factory=list)
    verification: list[VerificationItem] = Field(default_factory=list)
    refused: bool = Field(
        default=False,
        description="True when the assistant refused (scripture alteration or moderation)",
    )
    moderated: bool = Field(
        default=False, description="True when moderation blocked or replaced content"
    )
    moderation: ModerationInfo | None = None
    intent: IntentInfo | None = None
    image_base64: str | None = None
    image_url: str | None = Field(
        default=None, description="Relative URL of the persisted image (durable store)"
    )
    session_id: str | None = Field(
        default=None, description="Echoes the request session_id when memory is used"
    )
    backend: BackendInfo


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    denomination: Denomination = Denomination.NEUTRAL
    top_k: int | None = Field(default=None, ge=1, le=50)


class SearchResponse(BaseModel):
    query: str
    denomination: Denomination
    citations: list[Citation]


class ImageRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Theme/subject to illustrate")
    denomination: Denomination = Denomination.NEUTRAL
    negative: str | None = Field(default=None, description="Optional negative-prompt override")


class ImageResponse(BaseModel):
    image_base64: str | None = None
    prompt_used: str | None = None
    negative_used: str | None = None
    refused: bool = False
    reason: str | None = None
    backend: str


class ComposeRequest(BaseModel):
    request: str = Field(..., min_length=1, description="Raw image request to compose")
    denomination: Denomination = Denomination.NEUTRAL
    negative: str | None = Field(default=None, description="Optional negative-prompt override")


class ComposeResponse(BaseModel):
    positive: str | None = None
    negative: str | None = None
    refused: bool = False
    reason: str | None = None
    backend: str


class VerifyRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text whose scripture refs are checked")


class VerifyResponse(BaseModel):
    text: str
    translation: str
    verification: list[VerificationItem]


class ModerateRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to screen")
    stage: Literal["input", "output"] = Field(
        default="input", description="Apply input-side or output-side rules"
    )


class ModerateResponse(BaseModel):
    allowed: bool
    stage: Literal["input", "output"]
    category: str | None = None
    reason: str | None = None


class SessionStateResponse(BaseModel):
    session_id: str
    summary: str
    recent: list[ChatMessage]
    turns: int


class SessionSummary(BaseModel):
    session_id: str
    denomination: str
    turns: int
    preview: str
    created_at: str | None = None
    updated_at: str | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


class HistoryTurn(BaseModel):
    role: str
    content: str
    intent_kind: str | None = None
    image_url: str | None = None
    created_at: str | None = None


class HistoryResponse(BaseModel):
    session_id: str
    turns: list[HistoryTurn]


class DependencyStatus(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    dependencies: list[DependencyStatus]
