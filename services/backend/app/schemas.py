"""Request/response models for the gateway API."""

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Latest user message")
    history: list[ChatMessage] = Field(
        default_factory=list, description="Prior turns, oldest first"
    )
    generate_image: bool = Field(
        default=False, description="Also generate a themed image for this turn"
    )


class BackendInfo(BaseModel):
    llm: str
    image: str


class ChatResponse(BaseModel):
    reply: str
    image_base64: str | None = None
    backend: BackendInfo


class DependencyStatus(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    dependencies: list[DependencyStatus]
