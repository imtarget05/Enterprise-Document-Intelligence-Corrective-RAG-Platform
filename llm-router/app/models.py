from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RoutingContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_type: str | None = None
    classification: str = "internal"  # confidential | internal | public

    document_count: int = Field(default=0, ge=0)
    page_count: int = Field(default=0, ge=0)
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    has_image: bool = False
    attachments: list[str | dict[str, Any]] = Field(default_factory=list)
    request_id: str | None = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[dict[str, Any]] = ""
    images: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    options: dict[str, Any] = Field(default_factory=dict)
    routing: RoutingContext = Field(default_factory=RoutingContext)
    provider: str | None = Field(
        default=None,
        description="AI provider: cloudflare, ollama, or local. Overrides default routing when provided.",
    )


class RouteDecision(BaseModel):
    provider: str = "cloudflare"
    model: str
    reason: str
    task_type: str
