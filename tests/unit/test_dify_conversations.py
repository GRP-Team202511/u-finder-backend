"""
Unit tests for src.services.dify_service.get_dify_conversations

These tests exercise the service layer directly (no router involvement)
by mocking the outbound httpx calls to Dify.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.dify_service import get_dify_conversations, DifyUpstreamError


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

FAKE_CONVERSATIONS = {
    "limit": 20,
    "has_more": False,
    "data": [
        {
            "id": "conv-aaa",
            "name": "New chat",
            "inputs": {},
            "status": "normal",
            "introduction": "",
            "created_at": 1679667915,
            "updated_at": 1679667915,
        },
    ],
}


def _build_get_client(*, status_code: int = 200, json_body: dict | None = None, content: bytes = b""):
    """
    Build a mock httpx.AsyncClient for GET requests (conversations endpoint).
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_body if json_body is not None else {}
    mock_response.text = json.dumps(json_body) if json_body is not None else content.decode(errors="replace")
    mock_response.content = content or json.dumps(json_body if json_body is not None else {}).encode()

    client = AsyncMock()
    client.get = AsyncMock(return_value=mock_response)

    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    return client_ctx, client


# ──────────────────────────────────────────────
# Tests: Configuration validation
# ──────────────────────────────────────────────

class TestConversationsConfigValidation:
    """Verify early-exit when required settings are missing."""

    async def test_empty_api_key_raises(self):
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = ""
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await get_dify_conversations(user="1")

            assert exc_info.value.status_code == 0
            assert b"DIFY_API_KEY" in exc_info.value.body

    async def test_empty_base_url_raises(self):
        with patch("src.services.dify_service.settings") as mock_settings:
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = ""
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await get_dify_conversations(user="1")

            assert b"DIFY_API_BASE_URL" in exc_info.value.body


# ──────────────────────────────────────────────
# Tests: Successful retrieval
# ──────────────────────────────────────────────

class TestConversationsSuccess:
    """Verify successful conversations retrieval returns correct data."""

    async def test_returns_conversations(self):
        client_ctx, _ = _build_get_client(status_code=200, json_body=FAKE_CONVERSATIONS)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            result = await get_dify_conversations(user="1")

        assert result == FAKE_CONVERSATIONS
        assert result["has_more"] is False
        assert len(result["data"]) == 1

    async def test_correct_url_and_params(self):
        """Verify the correct Dify URL and query params are sent."""
        client_ctx, mock_client = _build_get_client(
            status_code=200, json_body=FAKE_CONVERSATIONS
        )

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            await get_dify_conversations(
                user="42",
                last_id="conv-abc",
                limit=10,
            )

        mock_client.get.assert_awaited_once()
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "https://api.dify.ai/v1/conversations"
        params = call_args[1]["params"]
        assert params["user"] == "42"
        assert params["last_id"] == "conv-abc"
        assert params["limit"] == 10
        assert params["sort_by"] == "-updated_at"

    async def test_empty_result(self):
        """Empty conversation list is returned correctly."""
        empty_response = {"limit": 20, "has_more": False, "data": []}
        client_ctx, _ = _build_get_client(status_code=200, json_body=empty_response)

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            result = await get_dify_conversations(user="1")

        assert result["data"] == []
        assert result["has_more"] is False


# ──────────────────────────────────────────────
# Tests: Error handling
# ──────────────────────────────────────────────

class TestConversationsErrors:
    """Verify DifyUpstreamError for non-200 responses."""

    async def test_500_raises(self):
        client_ctx, _ = _build_get_client(status_code=500, content=b"Internal Server Error")

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await get_dify_conversations(user="1")

            assert exc_info.value.status_code == 500

    async def test_401_raises(self):
        client_ctx, _ = _build_get_client(status_code=401, content=b"Unauthorized")

        with patch("src.services.dify_service.settings") as mock_settings, \
             patch("src.services.dify_service.httpx.AsyncClient", return_value=client_ctx):
            mock_settings.dify_api_key = "app-test"
            mock_settings.dify_api_base_url = "https://api.dify.ai/v1"
            mock_settings.dify_timeout = 60

            with pytest.raises(DifyUpstreamError) as exc_info:
                await get_dify_conversations(user="1")

            assert exc_info.value.status_code == 401

    async def test_network_error_raises(self):
        """httpx.RequestError → DifyUpstreamError(502)."""
        import httpx

        client = AsyncMock()
        client.get = AsyncMock(
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
                await get_dify_conversations(user="1")

            assert exc_info.value.status_code == 502
