# This code was completed by GRP Team 2025.11.
"""
Chat related Pydantic models
"""
from typing import Any, Literal, Optional
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


# ============ Chat Messages (History) ============
class MessageFile(BaseModel):
    """File attached to a message."""
    id: str
    type: str
    url: str
    belongs_to: str


class Feedback(BaseModel):
    """User feedback on a message."""
    rating: str = Field(..., description="Upvote as 'like' / Downvote as 'dislike'")


class AgentThought(BaseModel):
    """Agent reasoning step."""
    id: str
    chain_id: Optional[Any] = None
    message_id: str
    position: int
    thought: str
    tool: str
    tool_input: str
    created_at: int
    observation: str
    files: list[str] = Field(default_factory=list)


class MessageItem(BaseModel):
    """A single message in conversation history."""
    id: str
    conversation_id: str
    inputs: dict = Field(default_factory=dict)
    query: str
    answer: str
    message_files: list[MessageFile] = Field(default_factory=list)
    feedback: Optional[Feedback] = None
    retriever_resources: list[str] = Field(default_factory=list)
    created_at: int
    agent_thoughts: list[AgentThought] = Field(default_factory=list)


class ChatMessagesResponse(BaseModel):
    """Response for GET /chat/messages."""
    limit: int = Field(..., description="Number of returned items")
    has_more: bool = Field(..., description="Whether there is a next page")
    data: list[MessageItem] = Field(..., description="Message list")


# ============ Conversations ============
class ConversationItem(BaseModel):
    """A single conversation in the list."""
    id: str
    name: str
    inputs: dict = Field(default_factory=dict)
    status: str
    introduction: Optional[str] = ""
    created_at: int
    updated_at: int


class ConversationsResponse(BaseModel):
    """Response for GET /chat/conversations."""
    limit: int = Field(..., description="Number of returned items")
    has_more: bool = Field(..., description="Whether there is a next page")
    data: list[ConversationItem] = Field(..., description="Conversation list")


# ============ Error ============
class ErrorResponse(BaseModel):
    """Generic error response."""
    message: str


class ValidationErrorResponse(BaseModel):
    """Validation error response from FastAPI/Pydantic."""
    detail: list[dict[str, Any]]


# ============ Feedback ============
class FeedbackRequest(BaseModel):
    """Request body for the message feedback endpoint."""
    rating: Optional[Literal["like", "dislike"]] = Field(
        ...,
        description="Feedback rating: 'like', 'dislike', or null to revoke.",
    )
    content: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional detailed feedback text.",
    )


class FeedbackResponse(BaseModel):
    """Response for the message feedback endpoint."""
    result: str


# ============ Stop Chat ============
class StopChatResponse(BaseModel):
    """Response for the stop generation endpoint."""
    result: str


# ============ Delete Conversation ============
class DeleteConversationResponse(BaseModel):
    """Response for the delete conversation endpoint."""
    result: str


# ============ Rename Conversation ============
class RenameConversationRequest(BaseModel):
    """Request body for the rename conversation endpoint."""
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="The new name / title for the conversation.",
    )


class RenameConversationResponse(BaseModel):
    """Response for the rename conversation endpoint."""
    result: str
