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


def _normalized_dify_base_url() -> str:
    """Return a normalized Dify API base URL without trailing slash."""
    return settings.dify_api_base_url.rstrip("/")


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
    base_url = _normalized_dify_base_url()
    chat_messages_url = f"{base_url}/chat-messages"

    is_first_turn = not conversation_id  # True when starting a new conversation
    payload = {
        "inputs": {"is_first_turn": str(is_first_turn).lower()},
        "query": query,
        "response_mode": "streaming",
        "conversation_id": conversation_id or "",
        "user": user,
    }

    headers = {
        "Authorization": f"Bearer {settings.dify_api_key}",
        "Content-Type": "application/json",
    }

    # Validate Dify configuration before making the request
    if not settings.dify_api_key:
        logger.error("DIFY_API_KEY is not configured")
        raise DifyUpstreamError(0, b"DIFY_API_KEY is not set")
    if not settings.dify_api_base_url:
        logger.error("DIFY_API_BASE_URL is not configured")
        raise DifyUpstreamError(0, b"DIFY_API_BASE_URL is not set")

    logger.info(
        "Dify request: user=%s conversation_id=%s query_len=%d",
        user,
        conversation_id or "(new)",
        len(query),
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.dify_timeout)) as client:
            async with client.stream(
                "POST",
                chat_messages_url,
                json=payload,
                headers=headers,
            ) as response:
                # If Dify returns a non-200 status, raise so the router can
                # report it as an SSE error event frame to the frontend.
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
    except httpx.RequestError as exc:
        logger.error("Dify stream request failed: %s", exc)
        raise DifyUpstreamError(502, str(exc).encode()) from exc


class DifyUpstreamError(Exception):
    """Raised when Dify returns a non-200 status code."""

    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Dify returned {status_code}")


async def stop_dify_chat(*, task_id: str, user: str) -> dict:
    """
    Call Dify ``POST /v1/chat-messages/:task_id/stop`` to abort an
    in-progress streaming generation.

    Args:
        task_id: The Dify task ID (from SSE events).
        user:    A stable user identifier (e.g. str(user_id)).

    Returns:
        The JSON response body from Dify (e.g. ``{"result": "success"}``).

    Raises:
        DifyUpstreamError: If Dify returns a non-200 status.
    """
    if not settings.dify_api_key:
        logger.error("DIFY_API_KEY is not configured")
        raise DifyUpstreamError(0, b"DIFY_API_KEY is not set")
    if not settings.dify_api_base_url:
        logger.error("DIFY_API_BASE_URL is not configured")
        raise DifyUpstreamError(0, b"DIFY_API_BASE_URL is not set")

    base_url = _normalized_dify_base_url()
    url = f"{base_url}/chat-messages/{task_id}/stop"
    headers = {
        "Authorization": f"Bearer {settings.dify_api_key}",
        "Content-Type": "application/json",
    }
    payload = {"user": user}

    logger.info("Dify stop request: task_id=%s user=%s", task_id, user)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.dify_timeout)) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        logger.error("Dify stop request failed: %s", exc)
        raise DifyUpstreamError(502, str(exc).encode()) from exc

    if response.status_code != 200:
        logger.error(
            "Dify stop returned status=%d body=%s",
            response.status_code,
            response.text[:500],
        )
        raise DifyUpstreamError(response.status_code, response.content)

    try:
        result = response.json()
    except ValueError as exc:
        logger.error("Dify stop returned invalid JSON: %s", response.text[:500])
        raise DifyUpstreamError(502, b"Invalid JSON response from Dify") from exc

    logger.info("Dify stop success: task_id=%s result=%s", task_id, result)
    return result


# ──────────────────────────────────────────────
# Dify GET /messages — conversation history
# ──────────────────────────────────────────────
DIFY_MESSAGES_URL = f"{settings.dify_api_base_url}/messages"


async def get_dify_messages(
    *,
    conversation_id: str,
    user: str,
    first_id: str = "",
    limit: int = 20,
) -> dict:
    """
    Call Dify ``GET /v1/messages`` to retrieve conversation history.

    Args:
        conversation_id: The Dify conversation UUID.
        user:            A stable user identifier (e.g. str(user_id)).
        first_id:        The ID of the first message on the current page
                         (empty string for the latest page).
        limit:           Number of messages to retrieve (1-100, default 20).

    Returns:
        A dict with keys ``limit``, ``has_more``, and ``data`` (list of
        message objects).

    Raises:
        DifyUpstreamError: If Dify returns a non-200 status code.
    """
    if not settings.dify_api_key:
        logger.error("DIFY_API_KEY is not configured")
        raise DifyUpstreamError(0, b"DIFY_API_KEY is not set")
    if not settings.dify_api_base_url:
        logger.error("DIFY_API_BASE_URL is not configured")
        raise DifyUpstreamError(0, b"DIFY_API_BASE_URL is not set")

    params = {
        "conversation_id": conversation_id,
        "user": user,
        "first_id": first_id,
        "limit": limit,
    }

    headers = {
        "Authorization": f"Bearer {settings.dify_api_key}",
    }

    logger.info(
        "Dify messages request: user=%s conversation_id=%s first_id=%s limit=%d",
        user,
        conversation_id,
        first_id or "(latest)",
        limit,
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.dify_timeout)) as client:
            response = await client.get(
                DIFY_MESSAGES_URL,
                params=params,
                headers=headers,
            )
    except httpx.RequestError as exc:
        logger.error("Dify messages request failed: %s", exc)
        raise DifyUpstreamError(502, str(exc).encode()) from exc

    if response.status_code != 200:
        logger.error(
            "Dify messages returned status=%d body=%s",
            response.status_code,
            response.text[:500],
        )
        raise DifyUpstreamError(response.status_code, response.content)

    data = response.json()
    logger.info(
        "Dify messages response: conversation_id=%s count=%d has_more=%s",
        conversation_id,
        len(data.get("data", [])),
        data.get("has_more"),
    )
    return data
