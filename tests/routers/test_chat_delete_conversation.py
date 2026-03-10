"""
Router tests for DELETE /chat/conversations/{conversation_id}
"""
from unittest.mock import patch, AsyncMock

from src.services.dify_service import DifyUpstreamError
from tests.routers.utils.response_asserts import (
    assert_message_response,
    assert_delete_conversation_200,
)


FAKE_BEARER_TOKEN = "fake-chat-test-token"


def _auth_headers():
    return {"Authorization": f"Bearer {FAKE_BEARER_TOKEN}"}


def _delete_url(conversation_id: str = "conv_abc") -> str:
    return f"/chat/conversations/{conversation_id}"


# ──────────────────────────────────────────────
# Tests: Authentication
# ──────────────────────────────────────────────

class TestDeleteConversationAuth:
    """Verify authentication gates on the delete conversation endpoint."""

    async def test_missing_auth_header_returns_422(self, client):
        """No Authorization header → 422."""
        resp = await client.delete(_delete_url())
        assert resp.status_code == 422

    async def test_invalid_bearer_token_returns_401(self, client, mock_db, mock_redis):
        """Invalid token → 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        resp = await client.delete(
            _delete_url(),
            headers=_auth_headers(),
        )
        assert resp.status_code == 401
        assert_message_response(resp.json(), "Invalid or expired token")


# ──────────────────────────────────────────────
# Tests: Happy path
# ──────────────────────────────────────────────

class TestDeleteConversationSuccess:
    """Verify successful conversation deletion."""

    async def test_delete_returns_success(self, client, mock_redis):
        """Valid delete request → 200 with result='success'."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.delete_dify_conversation",
            new_callable=AsyncMock,
            return_value={"result": "success"},
        ):
            resp = await client.delete(
                _delete_url(),
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert_delete_conversation_200(resp.json())

    async def test_passes_correct_params_to_service(self, client, mock_redis):
        """Verify conversation_id and user are forwarded correctly."""
        mock_redis.hgetall.return_value = {"user_id": "42", "user_agent": "pytest"}

        captured_kwargs = {}

        async def _capture_delete(**kwargs):
            captured_kwargs.update(kwargs)
            return {"result": "success"}

        with patch(
            "src.routers.chat.delete_dify_conversation",
            side_effect=_capture_delete,
        ):
            resp = await client.delete(
                _delete_url("c91daa90-262c-4e0a-b066-a2a2e295f81b"),
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert captured_kwargs["conversation_id"] == "c91daa90-262c-4e0a-b066-a2a2e295f81b"
        assert captured_kwargs["user"] == "42"


# ──────────────────────────────────────────────
# Tests: Error handling
# ──────────────────────────────────────────────

class TestDeleteConversationErrors:
    """Verify error handling for the delete conversation endpoint."""

    async def test_dify_404_returns_404(self, client, mock_redis):
        """Dify conversation not found → 404."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.delete_dify_conversation",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(404, b"Not Found"),
        ):
            resp = await client.delete(
                _delete_url("nonexistent_conv"),
                headers=_auth_headers(),
            )

        assert resp.status_code == 404
        assert_message_response(resp.json(), "Conversation not found")

    async def test_dify_502_returns_502(self, client, mock_redis):
        """Dify upstream error → 502."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.delete_dify_conversation",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(502, b"Bad Gateway"),
        ):
            resp = await client.delete(
                _delete_url(),
                headers=_auth_headers(),
            )

        assert resp.status_code == 502
        assert_message_response(resp.json(), "Dify service unavailable")

    async def test_dify_config_error_returns_502(self, client, mock_redis):
        """Dify config missing (status_code=0) → 502."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.delete_dify_conversation",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(0, b"DIFY_API_KEY is not set"),
        ):
            resp = await client.delete(
                _delete_url(),
                headers=_auth_headers(),
            )

        assert resp.status_code == 502
        assert_message_response(resp.json(), "Dify service unavailable")

    async def test_unexpected_exception_returns_500(self, client, mock_redis):
        """Unexpected runtime error → 500."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.delete_dify_conversation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("something broke"),
        ):
            resp = await client.delete(
                _delete_url(),
                headers=_auth_headers(),
            )

        assert resp.status_code == 500
        assert_message_response(resp.json(), "Internal server error")
