"""
Chat related Pydantic models
"""
from typing import Any

from pydantic import BaseModel, Field


# ============ Chat Stream ============
class ChatStreamRequest(BaseModel):
    """Request body for the SSE chat endpoint."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The user's input message / question.",
    )


# ============ Error ============
class ErrorResponse(BaseModel):
    """Generic error response."""
    message: str


class ValidationErrorResponse(BaseModel):
    """Validation error response from FastAPI/Pydantic."""
    detail: list[dict[str, Any]]


# ============ Stop Chat ============
class StopChatResponse(BaseModel):
    """Response for the stop generation endpoint."""
    result: str
