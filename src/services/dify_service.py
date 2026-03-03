"""
Dify API service module
Handles communication with the Dify AI platform via SSE streaming
and file-based CV parsing.
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


# ──────────────────────────────────────────────
# Dify GET /conversations — conversation list
# ──────────────────────────────────────────────


async def get_dify_conversations(
    *,
    user: str,
    last_id: str = "",
    limit: int = 20,
    sort_by: str = "-updated_at",
) -> dict:
    """
    Call Dify ``GET /v1/conversations`` to retrieve the user's
    conversation list.

    Args:
        user:     A stable user identifier (e.g. str(user_id)).
        last_id:  ID of the last item on the current page (cursor).
        limit:    Number of conversations to retrieve (1-100, default 20).
        sort_by:  Sort field, default ``-updated_at``.

    Returns:
        A dict with keys ``limit``, ``has_more``, and ``data``.

    Raises:
        DifyUpstreamError: If Dify returns a non-200 status code.
    """
    if not settings.dify_api_key:
        logger.error("DIFY_API_KEY is not configured")
        raise DifyUpstreamError(0, b"DIFY_API_KEY is not set")
    if not settings.dify_api_base_url:
        logger.error("DIFY_API_BASE_URL is not configured")
        raise DifyUpstreamError(0, b"DIFY_API_BASE_URL is not set")

    base_url = _normalized_dify_base_url()
    url = f"{base_url}/conversations"
    params = {
        "user": user,
        "last_id": last_id,
        "limit": limit,
        "sort_by": sort_by,
    }
    headers = {
        "Authorization": f"Bearer {settings.dify_api_key}",
    }

    logger.info(
        "Dify conversations request: user=%s last_id=%s limit=%d",
        user,
        last_id or "(first page)",
        limit,
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.dify_timeout)) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.RequestError as exc:
        logger.error("Dify conversations request failed: %s", exc)
        raise DifyUpstreamError(502, str(exc).encode()) from exc

    if response.status_code != 200:
        logger.error(
            "Dify conversations returned status=%d body=%s",
            response.status_code,
            response.text[:500],
        )
        raise DifyUpstreamError(response.status_code, response.content)

    data = response.json()
    logger.info(
        "Dify conversations response: user=%s count=%d has_more=%s",
        user,
        len(data.get("data", [])),
        data.get("has_more"),
    )
    return data


# ──────────────────────────────────────────────
# Dify POST /messages/:message_id/feedbacks
# ──────────────────────────────────────────────


async def submit_dify_feedback(
    *,
    message_id: str,
    rating: Optional[str],
    user: str,
    content: Optional[str] = None,
) -> dict:
    """
    Call Dify ``POST /v1/messages/:message_id/feedbacks`` to submit
    user feedback (like / dislike / revoke) on a message.

    Args:
        message_id: The Dify message UUID.
        rating:     ``"like"``, ``"dislike"``, or ``None`` to revoke.
        user:       A stable user identifier (e.g. str(user_id)).
        content:    Optional free-text feedback detail.

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
    url = f"{base_url}/messages/{message_id}/feedbacks"
    headers = {
        "Authorization": f"Bearer {settings.dify_api_key}",
        "Content-Type": "application/json",
    }
    payload: dict = {"rating": rating, "user": user}
    if content is not None:
        payload["content"] = content

    logger.info(
        "Dify feedback request: message_id=%s rating=%s user=%s",
        message_id,
        rating,
        user,
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.dify_timeout)) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        logger.error("Dify feedback request failed: %s", exc)
        raise DifyUpstreamError(502, str(exc).encode()) from exc

    if response.status_code != 200:
        logger.error(
            "Dify feedback returned status=%d body=%s",
            response.status_code,
            response.text[:500],
        )
        raise DifyUpstreamError(response.status_code, response.content)

    try:
        result = response.json()
    except ValueError as exc:
        logger.error("Dify feedback returned invalid JSON: %s", response.text[:500])
        raise DifyUpstreamError(502, b"Invalid JSON response from Dify") from exc

    logger.info("Dify feedback success: message_id=%s result=%s", message_id, result)
    return result


# ──────────────────────────────────────────────
# Dify DELETE /conversations/:conversation_id
# ──────────────────────────────────────────────


async def delete_dify_conversation(
    *,
    conversation_id: str,
    user: str,
) -> dict:
    """
    Call Dify ``DELETE /v1/conversations/:conversation_id`` to permanently
    delete a conversation and all its messages.

    Args:
        conversation_id: The Dify conversation UUID.
        user:            A stable user identifier (e.g. str(user_id)).

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
    url = f"{base_url}/conversations/{conversation_id}"
    headers = {
        "Authorization": f"Bearer {settings.dify_api_key}",
        "Content-Type": "application/json",
    }
    payload = {"user": user}

    logger.info(
        "Dify delete conversation request: conversation_id=%s user=%s",
        conversation_id,
        user,
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.dify_timeout)) as client:
            response = await client.delete(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        logger.error("Dify delete conversation request failed: %s", exc)
        raise DifyUpstreamError(502, str(exc).encode()) from exc

    if response.status_code != 200:
        logger.error(
            "Dify delete conversation returned status=%d body=%s",
            response.status_code,
            response.text[:500],
        )
        raise DifyUpstreamError(response.status_code, response.content)

    try:
        result = response.json()
    except ValueError as exc:
        logger.error(
            "Dify delete conversation returned invalid JSON: %s",
            response.text[:500],
        )
        raise DifyUpstreamError(502, b"Invalid JSON response from Dify") from exc

    logger.info(
        "Dify delete conversation success: conversation_id=%s result=%s",
        conversation_id,
        result,
    )
    return result


# ──────────────────────────────────────────────
# Dify POST /conversations/:conversation_id/name
# ──────────────────────────────────────────────


async def rename_dify_conversation(
    *,
    conversation_id: str,
    name: str,
    user: str,
) -> dict:
    """
    Call Dify ``POST /v1/conversations/:conversation_id/name`` to rename
    a conversation.

    Args:
        conversation_id: The Dify conversation UUID.
        name:            The new conversation title.
        user:            A stable user identifier (e.g. str(user_id)).

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
    url = f"{base_url}/conversations/{conversation_id}/name"
    headers = {
        "Authorization": f"Bearer {settings.dify_api_key}",
        "Content-Type": "application/json",
    }
    payload = {"name": name, "user": user}

    logger.info(
        "Dify rename conversation request: conversation_id=%s name=%s user=%s",
        conversation_id,
        name,
        user,
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.dify_timeout)) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        logger.error("Dify rename conversation request failed: %s", exc)
        raise DifyUpstreamError(502, str(exc).encode()) from exc

    if response.status_code != 200:
        logger.error(
            "Dify rename conversation returned status=%d body=%s",
            response.status_code,
            response.text[:500],
        )
        raise DifyUpstreamError(response.status_code, response.content)

    try:
        result = response.json()
    except ValueError as exc:
        logger.error(
            "Dify rename conversation returned invalid JSON: %s",
            response.text[:500],
        )
        raise DifyUpstreamError(502, b"Invalid JSON response from Dify") from exc

    logger.info(
        "Dify rename conversation success: conversation_id=%s result=%s",
        conversation_id,
        result,
    )
    return result


# ──────────────────────────────────────────────
# CV Parsing via Dify Workflow
# ──────────────────────────────────────────────

async def upload_file_to_dify(
    *,
    file_content: bytes,
    filename: str,
    content_type: str,
    user: str,
) -> str:
    """
    Upload a file to Dify via ``POST /files/upload``.

    Args:
        file_content: Raw bytes of the file.
        filename:     Original filename (e.g. ``"resume.pdf"``).
        content_type: MIME type (e.g. ``"application/pdf"``).
        user:         A stable user identifier.

    Returns:
        The ``upload_file_id`` returned by Dify.

    Raises:
        DifyUpstreamError: If Dify returns a non-201/200 status or an
                           unexpected response body.
    """
    if not settings.dify_workflow_api_key:
        logger.error("DIFY_WORKFLOW_API_KEY is not configured")
        raise DifyUpstreamError(0, b"DIFY_WORKFLOW_API_KEY is not set")
    if not settings.dify_api_base_url:
        logger.error("DIFY_API_BASE_URL is not configured")
        raise DifyUpstreamError(0, b"DIFY_API_BASE_URL is not set")

    base_url = _normalized_dify_base_url()
    url = f"{base_url}/files/upload"
    headers = {
        "Authorization": f"Bearer {settings.dify_workflow_api_key}",
    }

    logger.info(
        "Dify file upload: user=%s filename=%s size=%d",
        user, filename, len(file_content),
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.dify_timeout)) as client:
            response = await client.post(
                url,
                headers=headers,
                files={"file": (filename, file_content, content_type)},
                data={"user": user},
            )
    except httpx.RequestError as exc:
        logger.error("Dify file upload request failed: %s", exc)
        raise DifyUpstreamError(502, str(exc).encode()) from exc

    if response.status_code not in (200, 201):
        logger.error(
            "Dify file upload returned status=%d body=%s",
            response.status_code,
            response.text[:500],
        )
        raise DifyUpstreamError(response.status_code, response.content)

    try:
        data = response.json()
    except ValueError as exc:
        logger.error("Dify file upload returned invalid JSON: %s", response.text[:500])
        raise DifyUpstreamError(502, b"Invalid JSON response from Dify") from exc

    upload_file_id = data.get("id")
    if not upload_file_id:
        logger.error("Dify file upload response missing 'id': %s", data)
        raise DifyUpstreamError(502, b"Dify file upload response missing file id")

    logger.info("Dify file uploaded: id=%s", upload_file_id)
    return upload_file_id


async def run_cv_parsing_workflow(
    *,
    upload_file_id: str,
    filename: str,
    user: str,
) -> dict:
    """
    Execute the Dify CV-parsing workflow in **blocking** mode via
    ``POST /workflows/run``.

    The workflow receives the uploaded file as an input variable and
    returns structured profile data in its ``outputs``.

    Args:
        upload_file_id: The file ID obtained from ``upload_file_to_dify``.
        filename:       Original filename, used only for logging (not
                        included in the Dify payload).
        user:           A stable user identifier.

    Returns:
        The ``outputs`` dict from the workflow execution result.

    Raises:
        DifyUpstreamError: If Dify returns a non-200 status, the workflow
                           fails, or the response cannot be parsed.
    """
    if not settings.dify_workflow_api_key:
        logger.error("DIFY_WORKFLOW_API_KEY is not configured")
        raise DifyUpstreamError(0, b"DIFY_WORKFLOW_API_KEY is not set")
    if not settings.dify_api_base_url:
        logger.error("DIFY_API_BASE_URL is not configured")
        raise DifyUpstreamError(0, b"DIFY_API_BASE_URL is not set")

    base_url = _normalized_dify_base_url()
    url = f"{base_url}/workflows/run"
    headers = {
        "Authorization": f"Bearer {settings.dify_workflow_api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "inputs": {
            "file": {
                "type": "document",
                "transfer_method": "local_file",
                "upload_file_id": upload_file_id,
            },
        },
        "response_mode": "blocking",
        "user": user,
    }

    logger.info(
        "Dify workflow run: user=%s upload_file_id=%s filename=%s",
        user, upload_file_id, filename,
    )

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.dify_timeout)
        ) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        logger.error("Dify workflow request failed: %s", exc)
        raise DifyUpstreamError(502, str(exc).encode()) from exc

    if response.status_code != 200:
        logger.error(
            "Dify workflow returned status=%d body=%s",
            response.status_code,
            response.text[:500],
        )
        raise DifyUpstreamError(response.status_code, response.content)

    try:
        result = response.json()
    except ValueError as exc:
        logger.error("Dify workflow returned invalid JSON: %s", response.text[:500])
        raise DifyUpstreamError(502, b"Invalid JSON response from Dify") from exc

    # Check workflow execution status
    data = result.get("data", {})
    status = data.get("status")
    if status != "succeeded":
        error_msg = data.get("error", "Unknown workflow error")
        logger.error("Dify workflow failed: status=%s error=%s", status, error_msg)
        raise DifyUpstreamError(
            422,
            f"Workflow execution failed: {error_msg}".encode(),
        )

    outputs = data.get("outputs")
    if not outputs or not isinstance(outputs, dict):
        logger.error("Dify workflow returned empty or invalid outputs: %s", data)
        raise DifyUpstreamError(
            422,
            b"Workflow returned no structured output",
        )

    logger.info(
        "Dify workflow succeeded: workflow_run_id=%s total_tokens=%s",
        result.get("workflow_run_id"),
        data.get("total_tokens"),
    )
    logger.info("Dify workflow outputs keys=%s", list(outputs.keys()))
    logger.info("Dify workflow outputs content=%s", json.dumps(outputs, ensure_ascii=False, default=str)[:3000])
    return outputs
