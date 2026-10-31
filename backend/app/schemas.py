"""
JARVIS Backend — Pydantic request / response schemas.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Chat ──────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    """User message sent to JARVIS."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The user's message text",
    )
    previous_interaction_id: str | None = Field(
        default=None,
        description="Optional ID from the previous interaction for multi-turn context",
    )


class ChatResponse(BaseModel):
    """JARVIS response from Gemini."""

    reply: str = Field(..., description="JARVIS response text")
    interaction_id: str = Field(
        ..., description="Interaction ID for multi-turn conversation"
    )
    model: str = Field(..., description="Model used for this response")


# ── Health ────────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    gemini_configured: bool
    model: str
