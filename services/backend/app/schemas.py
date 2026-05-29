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
        default_factory=list, description="Prior turns, oldest first"
    )
    denomination: Denomination = Field(
        default=Denomination.NEUTRAL,
        description="Filters which canon books are eligible for grounding",
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
        default=False, description="True when the assistant refused to alter scripture"
    )
    image_base64: str | None = None
    backend: BackendInfo


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    denomination: Denomination = Denomination.NEUTRAL
    top_k: int | None = Field(default=None, ge=1, le=50)


class SearchResponse(BaseModel):
    query: str
    denomination: Denomination
    citations: list[Citation]


class VerifyRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text whose scripture refs are checked")


class VerifyResponse(BaseModel):
    text: str
    translation: str
    verification: list[VerificationItem]


class DependencyStatus(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    dependencies: list[DependencyStatus]
