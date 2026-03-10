"""
Unit tests for src.services.dify_service
(stream_dify_chat, stop_dify_chat & delete_dify_conversation)

These tests exercise the service layer directly (no router involvement)
by mocking the outbound httpx calls to Dify.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.dify_service import stream_dify_chat, stop_dify_chat, delete_dify_conversation, rename_dify_conversation, DifyUpstreamError


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_mock_response(*, status_code: int = 200, sse_lines: list[str] | None = None, body: bytes = b""):
    """
    Build a mock httpx streaming response.

    Args:
        status_code: HTTP status code to simulate.
        sse_lines:   List of raw SSE lines the mock ``aiter_lines()`` will yield.
        body:        Raw body returned by ``aread()`` (for non-200 cases).
    """
    response = AsyncMock()
    response.status_code = status_code
    response.aread = AsyncMock(return_value=body)

    async def _aiter_lines():
        for line in (sse_lines or []):
            yield line

    response.aiter_lines = _aiter_lines

    return response


def _build_client_ctx(mock_response):
    """
    Return a mock ``httpx.AsyncClient`` whose ``.stream()`` context manager
    yields ``mock_response``.

    httpx.AsyncClient is used as ``async with httpx.AsyncClient(...) as client``
    and then ``async with client.stream(...) as response``.
    Both are async context managers.
    """
    # Inner: client.stream() -> async context manager yielding mock_response
    stream_ctx = MagicMock()
    stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    stream_ctx.__aexit__ = AsyncMock(return_value=False)

    client = MagicMock()
    client.stream.return_value = stream_ctx

    # Outer: httpx.AsyncClient() -> async context manager yielding client
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    return client_ctx


# ──────────────────────────────────────────────
# Tests: Configuration validation
# ──────────────────────────────────────────────

class TestDifyConfigValidation:
    """Verify early-exit when required settings are missing."""

    async def test_empty_api_key_raises(self):
        """DIFY_API_KEY='' should raise DifyUpstreamError before any HTTP call."""
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = ""
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                async for _ in stream_dify_chat(query="hi", user="1"):
                    pass  # pragma: no cover

            assert exc_info.value.status_code == 0
            assert b"DIFY_API_KEY" in exc_info.value.body

    async def test_empty_base_url_raises(self):
        """DIFY_API_BASE_URL='' should raise DifyUpstreamError."""
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = ""
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                async for _ in stream_dify_chat(query="hi", user="1"):
                    pass  # pragma: no cover

            assert b"DIFY_API_BASE_URL" in exc_info.value.body


# ──────────────────────────────────────────────
# Tests: Non-200 from Dify
# ──────────────────────────────────────────────

class TestDifyNon200:
    """Verify DifyUpstreamError is raised for non-200 responses."""

    async def test_502_raises_dify_upstream_error(self):
        mock_resp = _make_mock_response(status_code=502, body=b"Bad Gateway")
        client_ctx = _build_client_ctx(mock_resp)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                async for _ in stream_dify_chat(query="hi", user="1"):
                    pass  # pragma: no cover

            assert exc_info.value.status_code == 502

    async def test_401_raises_dify_upstream_error(self):
        mock_resp = _make_mock_response(status_code=401, body=b"Unauthorized")
        client_ctx = _build_client_ctx(mock_resp)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                async for _ in stream_dify_chat(query="hi", user="1"):
                    pass  # pragma: no cover

            assert exc_info.value.status_code == 401


# ──────────────────────────────────────────────
# Tests: SSE line filtering
# ──────────────────────────────────────────────

class TestDifySSEFiltering:
    """Verify only 'data:' lines are yielded and non-data lines are skipped."""

    async def test_only_data_lines_yielded(self):
        """Blank lines, comments, and event: lines should be filtered out."""
        sse_lines = [
            "",
            "event: message",
            'data: {"event": "agent_message", "answer": "hello"}',
            "",
            ": keep-alive comment",
            'data: {"event": "message_end", "metadata": {}}',
        ]
        mock_resp = _make_mock_response(status_code=200, sse_lines=sse_lines)
        client_ctx = _build_client_ctx(mock_resp)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            frames = []
            async for frame in stream_dify_chat(query="hi", user="1"):
                frames.append(frame)

        # Should only yield the two data: lines
        assert len(frames) == 2
        for frame in frames:
            assert frame.startswith("data:")
            assert frame.endswith("\n\n")

    async def test_yields_correct_sse_format(self):
        """Each yielded frame should end with double newline."""
        sse_lines = [
            'data: {"event": "agent_message", "answer": "A"}',
        ]
        mock_resp = _make_mock_response(status_code=200, sse_lines=sse_lines)
        client_ctx = _build_client_ctx(mock_resp)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            frames = []
            async for frame in stream_dify_chat(query="hi", user="1"):
                frames.append(frame)

        assert len(frames) == 1
        assert frames[0] == 'data: {"event": "agent_message", "answer": "A"}\n\n'


# ──────────────────────────────────────────────
# Tests: Malformed JSON resilience
# ──────────────────────────────────────────────

class TestDifyMalformedJSON:
    """Verify the generator doesn't crash on malformed JSON in data: lines."""

    async def test_malformed_json_still_yielded(self):
        """
        Even if a data: line contains invalid JSON, it should still be
        yielded (the frontend decides what to do). The internal logging
        should not blow up.
        """
        sse_lines = [
            "data: NOT_VALID_JSON",
            'data: {"event": "message_end", "metadata": {}}',
        ]
        mock_resp = _make_mock_response(status_code=200, sse_lines=sse_lines)
        client_ctx = _build_client_ctx(mock_resp)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            frames = []
            async for frame in stream_dify_chat(query="hi", user="1"):
                frames.append(frame)

        # Both lines should be yielded, malformed or not
        assert len(frames) == 2
        assert "NOT_VALID_JSON" in frames[0]


# ══════════════════════════════════════════════
# stop_dify_chat tests
# ══════════════════════════════════════════════

def _build_post_client(*, status_code: int = 200, json_body: dict | None = None, content: bytes = b""):
    """
    Build a mock httpx.AsyncClient for non-streaming POST (stop endpoint).
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_body if json_body is not None else {}
    mock_response.text = json.dumps(json_body) if json_body is not None else content.decode(errors="replace")
    mock_response.content = content or json.dumps(json_body if json_body is not None else {}).encode()

    client = AsyncMock()
    client.post = AsyncMock(return_value=mock_response)

    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    return client_ctx


class TestStopDifyConfigValidation:
    """Verify early-exit when required settings are missing."""

    async def test_empty_api_key_raises(self):
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = ""
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await stop_dify_chat(task_id="t1", user="1")

            assert b"DIFY_API_KEY" in exc_info.value.body

    async def test_empty_base_url_raises(self):
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = ""
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await stop_dify_chat(task_id="t1", user="1")

            assert b"DIFY_API_BASE_URL" in exc_info.value.body


class TestStopDifySuccess:
    """Verify successful stop returns the JSON body."""

    async def test_returns_result(self):
        client_ctx = _build_post_client(status_code=200, json_body={"result": "success"})

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            result = await stop_dify_chat(task_id="task_abc", user="1")

        assert result == {"result": "success"}


class TestStopDifyErrors:
    """Verify DifyUpstreamError for non-200 responses."""

    async def test_404_raises(self):
        client_ctx = _build_post_client(status_code=404, content=b"Not Found")

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await stop_dify_chat(task_id="t_gone", user="1")

            assert exc_info.value.status_code == 404

    async def test_500_raises(self):
        client_ctx = _build_post_client(status_code=500, content=b"Internal Server Error")

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await stop_dify_chat(task_id="t1", user="1")

            assert exc_info.value.status_code == 500


# ══════════════════════════════════════════════
# delete_dify_conversation tests
# ══════════════════════════════════════════════

def _build_delete_client(*, status_code: int = 200, json_body: dict | None = None, content: bytes = b"",
                          invalid_json: bool = False):
    """
    Build a mock httpx.AsyncClient for DELETE (delete conversation endpoint).
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.text = json.dumps(json_body) if json_body is not None else content.decode(errors="replace")
    mock_response.content = content or json.dumps(json_body if json_body is not None else {}).encode()

    if invalid_json:
        mock_response.json.side_effect = ValueError("Invalid JSON")
    else:
        mock_response.json.return_value = json_body if json_body is not None else {}

    client = AsyncMock()
    client.request = AsyncMock(return_value=mock_response)

    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    return client_ctx


class TestDeleteConversationConfigValidation:
    """Verify early-exit when required settings are missing."""

    async def test_empty_api_key_raises(self):
        """DIFY_API_KEY='' should raise DifyUpstreamError before any HTTP call."""
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = ""
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await delete_dify_conversation(conversation_id="conv1", user="1")

            assert exc_info.value.status_code == 0
            assert b"DIFY_API_KEY" in exc_info.value.body

    async def test_empty_base_url_raises(self):
        """DIFY_API_BASE_URL='' should raise DifyUpstreamError."""
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = ""
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await delete_dify_conversation(conversation_id="conv1", user="1")

            assert b"DIFY_API_BASE_URL" in exc_info.value.body


class TestDeleteConversationSuccess:
    """Verify successful delete returns the JSON body."""

    async def test_returns_result(self):
        """Dify returns 204 → dict with result='success'."""
        client_ctx = _build_delete_client(status_code=204)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            result = await delete_dify_conversation(conversation_id="conv_abc", user="1")

        assert result == {"result": "success"}

    async def test_calls_correct_url_and_payload(self):
        """Verify the service calls Dify with the correct URL and user payload."""
        client_ctx = _build_delete_client(status_code=204)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx) as mock_client_cls:
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            await delete_dify_conversation(conversation_id="conv_xyz", user="42")

        # Get the actual client instance from the context manager
        client_instance = client_ctx.__aenter__.return_value
        client_instance.request.assert_called_once()
        call_args = client_instance.request.call_args
        assert call_args[0][0] == "DELETE"
        assert "conversations/conv_xyz" in call_args[0][1]
        assert call_args[1]["json"] == {"user": "42"}


class TestDeleteConversationErrors:
    """Verify DifyUpstreamError for non-200 responses and edge cases."""

    async def test_404_raises(self):
        """Dify returns 404 → DifyUpstreamError with status_code=404."""
        client_ctx = _build_delete_client(status_code=404, content=b"Not Found")

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await delete_dify_conversation(conversation_id="gone", user="1")

            assert exc_info.value.status_code == 404

    async def test_500_raises(self):
        """Dify returns 500 → DifyUpstreamError with status_code=500."""
        client_ctx = _build_delete_client(status_code=500, content=b"Internal Server Error")

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await delete_dify_conversation(conversation_id="conv1", user="1")

            assert exc_info.value.status_code == 500

    async def test_network_error_raises_502(self):
        """httpx.RequestError → DifyUpstreamError with status_code=502."""
        import httpx

        client = AsyncMock()
        client.request = AsyncMock(
            side_effect=httpx.RequestError("Connection refused")
        )
        client_ctx = MagicMock()
        client_ctx.__aenter__ = AsyncMock(return_value=client)
        client_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await delete_dify_conversation(conversation_id="conv1", user="1")

            assert exc_info.value.status_code == 502

    async def test_non_204_raises(self):
        """Dify returns 200 instead of 204 → DifyUpstreamError."""
        client_ctx = _build_delete_client(status_code=200, json_body={"result": "success"})

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await delete_dify_conversation(conversation_id="conv1", user="1")

            assert exc_info.value.status_code == 200


# ══════════════════════════════════════════════
# rename_dify_conversation tests
# ══════════════════════════════════════════════

def _build_rename_client(*, status_code: int = 200, json_body: dict | None = None, content: bytes = b"",
                          invalid_json: bool = False):
    """
    Build a mock httpx.AsyncClient for POST (rename conversation endpoint).
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.text = json.dumps(json_body) if json_body is not None else content.decode(errors="replace")
    mock_response.content = content or json.dumps(json_body if json_body is not None else {}).encode()

    if invalid_json:
        mock_response.json.side_effect = ValueError("Invalid JSON")
    else:
        mock_response.json.return_value = json_body if json_body is not None else {}

    client = AsyncMock()
    client.post = AsyncMock(return_value=mock_response)

    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    return client_ctx


class TestRenameConversationConfigValidation:
    """Verify early-exit when required settings are missing."""

    async def test_empty_api_key_raises(self):
        """DIFY_API_KEY='' should raise DifyUpstreamError before any HTTP call."""
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = ""
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await rename_dify_conversation(conversation_id="conv1", name="New Name", user="1")

            assert exc_info.value.status_code == 0
            assert b"DIFY_API_KEY" in exc_info.value.body

    async def test_empty_base_url_raises(self):
        """DIFY_API_BASE_URL='' should raise DifyUpstreamError."""
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = ""
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await rename_dify_conversation(conversation_id="conv1", name="New Name", user="1")

            assert b"DIFY_API_BASE_URL" in exc_info.value.body


class TestRenameConversationSuccess:
    """Verify successful rename returns the JSON body."""

    async def test_returns_result(self):
        """Dify returns 200 → dict with result='success'."""
        client_ctx = _build_rename_client(status_code=200, json_body={"result": "success"})

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            result = await rename_dify_conversation(conversation_id="conv_abc", name="New Title", user="1")

        assert result == {"result": "success"}

    async def test_calls_correct_url_and_payload(self):
        """Verify the service calls Dify with the correct URL and payload (name + user)."""
        client_ctx = _build_rename_client(status_code=200, json_body={"result": "success"})

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            await rename_dify_conversation(conversation_id="conv_xyz", name="Updated Title", user="42")

        client_instance = client_ctx.__aenter__.return_value
        client_instance.post.assert_called_once()
        call_args = client_instance.post.call_args
        assert "conversations/conv_xyz/name" in call_args[0][0]
        assert call_args[1]["json"] == {"name": "Updated Title", "user": "42"}


class TestRenameConversationErrors:
    """Verify DifyUpstreamError for non-200 responses and edge cases."""

    async def test_404_raises(self):
        """Dify returns 404 → DifyUpstreamError with status_code=404."""
        client_ctx = _build_rename_client(status_code=404, content=b"Not Found")

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await rename_dify_conversation(conversation_id="gone", name="X", user="1")

            assert exc_info.value.status_code == 404

    async def test_500_raises(self):
        """Dify returns 500 → DifyUpstreamError with status_code=500."""
        client_ctx = _build_rename_client(status_code=500, content=b"Internal Server Error")

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await rename_dify_conversation(conversation_id="conv1", name="X", user="1")

            assert exc_info.value.status_code == 500

    async def test_network_error_raises_502(self):
        """httpx.RequestError → DifyUpstreamError with status_code=502."""
        import httpx

        client = AsyncMock()
        client.post = AsyncMock(
            side_effect=httpx.RequestError("Connection refused")
        )
        client_ctx = MagicMock()
        client_ctx.__aenter__ = AsyncMock(return_value=client)
        client_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await rename_dify_conversation(conversation_id="conv1", name="X", user="1")

            assert exc_info.value.status_code == 502

    async def test_invalid_json_response_raises_502(self):
        """Dify returns 200 but invalid JSON → DifyUpstreamError(502)."""
        client_ctx = _build_rename_client(status_code=200, invalid_json=True)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await rename_dify_conversation(conversation_id="conv1", name="X", user="1")

            assert exc_info.value.status_code == 502
