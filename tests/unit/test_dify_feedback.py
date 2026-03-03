"""
Unit tests for src.services.dify_service.submit_dify_feedback

These tests exercise the service layer directly (no router involvement)
by mocking the outbound httpx calls to Dify.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.dify_service import submit_dify_feedback, DifyUpstreamError


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _build_post_client(*, status_code: int = 200, json_body: dict | None = None, content: bytes = b""):
    """
    Build a mock httpx.AsyncClient for non-streaming POST (feedback endpoint).
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_body or {}
    mock_response.text = json.dumps(json_body) if json_body else content.decode(errors="replace")
    mock_response.content = content or json.dumps(json_body or {}).encode()

    client = AsyncMock()
    client.post = AsyncMock(return_value=mock_response)

    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    return client_ctx, client


# ──────────────────────────────────────────────
# Tests: Configuration validation
# ──────────────────────────────────────────────

class TestFeedbackConfigValidation:
    """Verify early-exit when required settings are missing."""

    async def test_empty_api_key_raises(self):
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = ""
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await submit_dify_feedback(message_id="m1", rating="like", user="1")

            assert exc_info.value.status_code == 0
            assert b"DIFY_API_KEY" in exc_info.value.body

    async def test_empty_base_url_raises(self):
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = ""
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await submit_dify_feedback(message_id="m1", rating="like", user="1")

            assert b"DIFY_API_BASE_URL" in exc_info.value.body


# ──────────────────────────────────────────────
# Tests: Successful feedback
# ──────────────────────────────────────────────

class TestFeedbackSuccess:
    """Verify successful feedback returns the JSON body."""

    async def test_like_returns_result(self):
        client_ctx, _ = _build_post_client(status_code=200, json_body={"result": "success"})

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            result = await submit_dify_feedback(message_id="msg_abc", rating="like", user="1")

        assert result == {"result": "success"}

    async def test_dislike_returns_result(self):
        client_ctx, _ = _build_post_client(status_code=200, json_body={"result": "success"})

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            result = await submit_dify_feedback(message_id="msg_abc", rating="dislike", user="1")

        assert result == {"result": "success"}

    async def test_null_rating_revokes(self):
        client_ctx, _ = _build_post_client(status_code=200, json_body={"result": "success"})

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            result = await submit_dify_feedback(message_id="msg_abc", rating=None, user="1")

        assert result == {"result": "success"}

    async def test_correct_url_constructed(self):
        """Verify the correct Dify URL and payload are sent."""
        client_ctx, mock_client = _build_post_client(
            status_code=200, json_body={"result": "success"}
        )

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            await submit_dify_feedback(
                message_id="msg_123",
                rating="like",
                user="42",
                content="Great answer!",
            )

        # Verify the POST was called with the correct URL and payload
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://api.dify.ai/v1/messages/msg_123/feedbacks"
        payload = call_args[1]["json"]
        assert payload["rating"] == "like"
        assert payload["user"] == "42"
        assert payload["content"] == "Great answer!"

    async def test_content_omitted_when_none(self):
        """When content is None, the 'content' key should not appear in the payload."""
        client_ctx, mock_client = _build_post_client(
            status_code=200, json_body={"result": "success"}
        )

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            await submit_dify_feedback(
                message_id="msg_123",
                rating="like",
                user="1",
            )

        payload = mock_client.post.call_args[1]["json"]
        assert "content" not in payload


# ──────────────────────────────────────────────
# Tests: Error handling
# ──────────────────────────────────────────────

class TestFeedbackErrors:
    """Verify DifyUpstreamError for non-200 responses."""

    async def test_404_raises(self):
        client_ctx, _ = _build_post_client(status_code=404, content=b"Not Found")

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await submit_dify_feedback(message_id="m_gone", rating="like", user="1")

            assert exc_info.value.status_code == 404

    async def test_500_raises(self):
        client_ctx, _ = _build_post_client(status_code=500, content=b"Internal Server Error")

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await submit_dify_feedback(message_id="m1", rating="like", user="1")

            assert exc_info.value.status_code == 500

    async def test_invalid_json_response_raises(self):
        """Dify returns 200 but non-JSON body → DifyUpstreamError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.text = "not json"
        mock_response.content = b"not json"

        client = AsyncMock()
        client.post = AsyncMock(return_value=mock_response)

        client_ctx = MagicMock()
        client_ctx.__aenter__ = AsyncMock(return_value=client)
        client_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await submit_dify_feedback(message_id="m1", rating="like", user="1")

            assert exc_info.value.status_code == 502

    async def test_network_error_raises(self):
        """httpx.RequestError → DifyUpstreamError(502)."""
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
                await submit_dify_feedback(message_id="m1", rating="like", user="1")

            assert exc_info.value.status_code == 502
