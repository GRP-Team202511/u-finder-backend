"""
Chat router module
Provides the SSE streaming chat endpoint that proxies Dify agent responses.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, status, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.config.logger import get_logger
from src.database import get_db, get_redis, RefreshToken
from src.schemas.chat import ChatStreamRequest
from src.services.dify_service import stream_dify_chat, DifyUpstreamError
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
