"""
Chat router module
Provides the SSE streaming chat endpoint that proxies Dify agent responses.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query, status, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.config.logger import get_logger
from src.database import get_db, get_redis, RefreshToken
from src.schemas.chat import (
    ChatStreamRequest,
    ChatMessagesResponse,
    FeedbackRequest,
    FeedbackResponse,
    StopChatResponse,
    DeleteConversationResponse,
    ErrorResponse,
    ValidationErrorResponse,
)
from src.services.dify_service import stream_dify_chat, stop_dify_chat, get_dify_messages, submit_dify_feedback, delete_dify_conversation, DifyUpstreamError
from src.utils.session_utils import get_session
from src.utils.password_utils import hash_token

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


# ──────────────────────────────────────────────
# Auth helper (mirrors profile.py pattern)
# ──────────────────────────────────────────────
async def _get_current_user_id(
    authorization: str,
    db: AsyncSession,
    redis: Optional[Redis],
) -> int:
    """
    Extract and verify the refresh token from Authorization header.
    Returns the user_id associated with the session.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        )

    token = authorization.replace("Bearer ", "")

    # 1. Try Redis cache first
    if redis is not None:
        session_data = await get_session(redis, token)
        if session_data:
            return int(session_data["user_id"])

    # 2. Fallback to database
    from sqlalchemy import select

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hashed == hash_token(token)
        )
    )
    refresh_record = result.scalar_one_or_none()

    if not refresh_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        )

    return refresh_record.user_id


# ──────────────────────────────────────────────
# GET /chat/messages — Conversation History
# ──────────────────────────────────────────────
@router.get(
    "/messages",
    response_model=ChatMessagesResponse,
    summary="Get Conversation History Messages",
    description=(
        "Returns historical chat records in a scrolling load format, "
        "with the first page returning the latest `limit` messages "
        "(i.e., in reverse order)."
    ),
    responses={
        401: {"description": "Unauthorized", "model": ErrorResponse},
        422: {"description": "Validation error"},
        502: {"description": "Dify service unavailable", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def get_messages(
    conversationId: str = Query(
        ...,
        description="Conversation ID (Dify conversation UUID)",
    ),
    first_id: str = Query(
        "",
        description="The ID of the first chat record on the current page. "
                    "Empty string returns the latest page.",
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Number of messages to return (1-100, default 20).",
    ),
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Retrieve conversation history messages from Dify.

    Query parameters:
    - **conversationId** (required): the Dify conversation UUID.
    - **first_id**: message ID for pagination cursor (empty = latest page).
    - **limit**: page size, 1‒100, default 20.
    """
    # Authenticate
    user_id = await _get_current_user_id(authorization, db, redis)
    logger.info(
        "Get messages: user_id=%s conversation_id=%s first_id=%s limit=%d",
        user_id,
        conversationId,
        first_id or "(latest)",
        limit,
    )

    try:
        result = await get_dify_messages(
            conversation_id=conversationId,
            user=str(user_id),
            first_id=first_id,
            limit=limit,
        )
        return result
    except DifyUpstreamError as exc:
        logger.error("Dify upstream error in get_messages: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "Dify service unavailable"},
        )
    except Exception as exc:
        logger.error(
            "Unexpected error in get_messages: %s", exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


# ──────────────────────────────────────────────
# SSE Chat Endpoint
# ──────────────────────────────────────────────
@router.post(
    "/{conversation_id}",
    summary="Chat Stream (SSE)",
    responses={
        200: {
            "description": "SSE stream opened successfully. Upstream errors "
                          "are reported as SSE `error` event frames within the stream.",
            "content": {"text/event-stream": {}},
        },
        401: {"description": "Unauthorized"},
        422: {"description": "Validation error"},
    },
)
async def chat_stream(
    conversation_id: Optional[str],
    body: ChatStreamRequest,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Accept a user message and return a Server-Sent Events stream.

    The backend forwards the request to Dify (``POST /v1/chat-messages``
    with ``response_mode=streaming``) and transparently proxies each SSE
    event back to the frontend.

    **SSE event sequence:**

    | event | occurrences | meaning |
    |---|---|---|
    | ``agent_thought`` | 0‥N | agent reasoning / tool call |
    | ``message_file`` | 0‥N | generated file (image, etc.) |
    | ``agent_message`` | 1‥N | incremental answer text chunk |
    | ``message_end`` | 1 | stream finished |
    """
    # Authenticate
    user_id = await _get_current_user_id(authorization, db, redis)
    logger.info(
        "Chat request: user_id=%s conversation_id=%s",
        user_id,
        conversation_id or "(new)",
    )

    # Normalise conversation_id: treat "null" / empty as None
    if conversation_id in (None, "", "null"):
        conversation_id = None

    # Build the SSE generator with error handling
    async def _event_generator():
        try:
            async for chunk in stream_dify_chat(
                query=body.message,
                user=str(user_id),
                conversation_id=conversation_id,
            ):
                yield chunk
        except asyncio.CancelledError:
            # Client disconnected / request cancelled — let it propagate
            # without logging noise or attempting to write to a dead stream.
            logger.debug("Chat stream cancelled (client disconnect)")
            raise
        except DifyUpstreamError as exc:
            logger.error("Dify upstream error: %s", exc)
            # Send an error event so the frontend knows what happened
            import json

            error_payload = json.dumps({
                "event": "error",
                "message": "Dify service unavailable",
                "status": exc.status_code,
            })
            yield f"data: {error_payload}\n\n"
        except Exception as exc:
            logger.error("Unexpected error during Dify streaming: %s", exc, exc_info=True)
            import json

            error_payload = json.dumps({
                "event": "error",
                "message": "Internal server error",
            })
            yield f"data: {error_payload}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ──────────────────────────────────────────────
# Stop Chat Generation Endpoint
# ──────────────────────────────────────────────
@router.post(
    "/{task_id}/stop",
    summary="Stop Chat Generation",
    response_model=StopChatResponse,
    responses={
        200: {
            "description": "Generation stopped successfully",
            "model": StopChatResponse,
            "content": {
                "application/json": {
                    "example": {"result": "success"}
                }
            },
        },
        401: {
            "description": "Unauthorized",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"message": "Invalid or expired token"}
                }
            },
        },
        404: {
            "description": "Task not found or already completed",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"message": "Task not found or already completed"}
                }
            },
        },
        422: {
            "description": "Validation error",
            "model": ValidationErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "type": "missing",
                                "loc": ["header", "Authorization"],
                                "msg": "Field required",
                                "input": None,
                            }
                        ]
                    }
                }
            },
        },
        502: {
            "description": "Dify upstream error",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"message": "Dify service unavailable"}
                }
            },
        },
    },
)
async def stop_chat(
    task_id: str,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Stop an in-progress streaming chat generation.

    Forwards the stop request to Dify ``POST /v1/chat-messages/:task_id/stop``
    and returns the result.
    """
    user_id = await _get_current_user_id(authorization, db, redis)
    logger.info("Stop chat request: user_id=%s task_id=%s", user_id, task_id)

    try:
        result = await stop_dify_chat(task_id=task_id, user=str(user_id))
    except DifyUpstreamError as exc:
        logger.error("Dify stop upstream error: %s", exc)
        # Dify returns 404 when the task doesn't exist or has already finished
        if exc.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Task not found or already completed"},
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "Dify service unavailable"},
        )

    return StopChatResponse(result=result.get("result", "success"))


# ──────────────────────────────────────────────
# Message Feedback Endpoint
# ──────────────────────────────────────────────
@router.post(
    "/messages/{message_id}/feedbacks",
    summary="Message Feedback",
    response_model=FeedbackResponse,
    responses={
        200: {
            "description": "Feedback submitted successfully",
            "model": FeedbackResponse,
            "content": {
                "application/json": {
                    "example": {"result": "success"}
                }
            },
        },
        401: {
            "description": "Unauthorized",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"message": "Invalid or expired token"}
                }
            },
        },
        404: {
            "description": "Message not found",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"message": "Message not found"}
                }
            },
        },
        422: {
            "description": "Validation error",
            "model": ValidationErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "type": "literal_error",
                                "loc": ["body", "rating"],
                                "msg": "Input should be 'like' or 'dislike'",
                                "input": "love",
                            }
                        ]
                    }
                }
            },
        },
        502: {
            "description": "Dify upstream error",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"message": "Dify service unavailable"}
                }
            },
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error"}
                }
            },
        },
    },
)
async def message_feedback(
    message_id: str,
    body: FeedbackRequest,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Submit feedback (like / dislike / revoke) for a specific chat message.

    - **like**: upvote the message
    - **dislike**: downvote the message
    - **null**: revoke previous feedback
    """
    user_id = await _get_current_user_id(authorization, db, redis)
    logger.info(
        "Feedback request: user_id=%s message_id=%s rating=%s",
        user_id,
        message_id,
        body.rating,
    )

    try:
        result = await submit_dify_feedback(
            message_id=message_id,
            rating=body.rating,
            user=str(user_id),
            content=body.content,
        )
    except DifyUpstreamError as exc:
        logger.error("Dify feedback upstream error: %s", exc)
        if exc.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Message not found"},
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "Dify service unavailable"},
        )
    except Exception as exc:
        logger.error(
            "Unexpected error in message_feedback: %s", exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )

    return FeedbackResponse(result=result.get("result", "success"))


# ──────────────────────────────────────────────
# Delete Conversation Endpoint
# ──────────────────────────────────────────────
@router.delete(
    "/conversations/{conversation_id}",
    summary="Delete Conversation",
    response_model=DeleteConversationResponse,
    responses={
        200: {
            "description": "Conversation deleted successfully",
            "model": DeleteConversationResponse,
            "content": {
                "application/json": {
                    "example": {"result": "success"}
                }
            },
        },
        401: {
            "description": "Unauthorized",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"message": "Invalid or expired token"}
                }
            },
        },
        404: {
            "description": "Conversation not found",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"message": "Conversation not found"}
                }
            },
        },
        422: {
            "description": "Validation error",
            "model": ValidationErrorResponse,
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "type": "string_type",
                                "loc": ["path", "conversationId"],
                                "msg": "Input should be a valid string",
                                "input": None,
                            }
                        ]
                    }
                }
            },
        },
        502: {
            "description": "Dify upstream error",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"message": "Dify service unavailable"}
                }
            },
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse,
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error"}
                }
            },
        },
    },
)
async def delete_conversation(
    conversation_id: str,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Delete a specific conversation permanently.

    Forwards the delete request to Dify
    ``DELETE /v1/conversations/:conversation_id`` with the authenticated
    user's ID and returns the result.
    """
    user_id = await _get_current_user_id(authorization, db, redis)
    logger.info(
        "Delete conversation request: user_id=%s conversation_id=%s",
        user_id,
        conversation_id,
    )

    try:
        result = await delete_dify_conversation(
            conversation_id=conversation_id,
            user=str(user_id),
        )
    except DifyUpstreamError as exc:
        logger.error("Dify delete conversation upstream error: %s", exc)
        if exc.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Conversation not found"},
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "Dify service unavailable"},
        )
    except Exception as exc:
        logger.error(
            "Unexpected error in delete_conversation: %s", exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )

    return DeleteConversationResponse(result=result.get("result", "success"))
