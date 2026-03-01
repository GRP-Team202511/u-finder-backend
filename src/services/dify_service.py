"""
Dify API service module
Handles communication with the Dify AI platform via SSE streaming.
"""
import json
from typing import AsyncGenerator, Optional

import httpx

from src.config.logger import get_logger
from src.config.settings import get_settings

logger = get_logger(__name__)
settings = get_settings()

# Dify streaming endpoint
DIFY_CHAT_MESSAGES_URL = f"{settings.dify_api_base_url}/chat-messages"


async def stream_dify_chat(
    *,
    query: str,
    user: str,
    conversation_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Call Dify ``POST /v1/chat-messages`` in streaming mode and yield each
    SSE ``data:`` line exactly as received so the backend can transparently
    proxy them to the frontend.

    Args:
        query:            The user's question text.
        user:             A stable user identifier (e.g. str(user_id)).
        conversation_id:  Existing Dify conversation UUID, or None / "" for
                          the first message.

    Yields:
        SSE frame strings in the form ``"data: {…}\\n\\n"`` ready to be
        written directly into a ``StreamingResponse``.
    """
    payload = {
        "inputs": {},
        "query": query,
        "response_mode": "streaming",
        "conversation_id": conversation_id or "",
        "user": user,
    }

    headers = {
        "Authorization": f"Bearer {settings.dify_api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        "Dify request: user=%s conversation_id=%s query_len=%d",
        user,
        conversation_id or "(new)",
        len(query),
    )

    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.dify_timeout)) as client:
        async with client.stream(
            "POST",
            DIFY_CHAT_MESSAGES_URL,
            json=payload,
            headers=headers,
        ) as response:
            # If Dify returns a non-2xx status, raise so the router can
            # convert it into a proper HTTP error for the frontend.
            if response.status_code != 200:
                body = await response.aread()
                logger.error(
                    "Dify returned status=%d body=%s",
                    response.status_code,
                    body.decode(errors="replace")[:500],
                )
                raise DifyUpstreamError(response.status_code, body)

            async for raw_line in response.aiter_lines():
                # Dify sends lines like "data: {...}" followed by blank lines.
                if not raw_line.startswith("data:"):
                    continue

                # Yield the line in standard SSE format
                yield raw_line + "\n\n"

                # Optionally log message_end for traceability
                try:
                    json_str = raw_line[len("data:"):].strip()
                    event_obj = json.loads(json_str)
                    if event_obj.get("event") == "message_end":
                        metadata = event_obj.get("metadata", {})
                        usage = metadata.get("usage", {})
                        logger.info(
                            "Dify stream ended: conversation_id=%s message_id=%s "
                            "total_tokens=%s latency=%s",
                            event_obj.get("conversation_id"),
                            event_obj.get("message_id"),
                            usage.get("total_tokens"),
                            usage.get("latency"),
                        )
                except (json.JSONDecodeError, KeyError):
                    pass


class DifyUpstreamError(Exception):
    """Raised when Dify returns a non-200 status code."""

    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Dify returned {status_code}")
