"""
Router tests for POST /chat/conversations/{conversation_id}/name
"""
from unittest.mock import patch, AsyncMock

from src.services.dify_service import DifyUpstreamError
from tests.routers.utils.response_asserts import (
    assert_message_response,
    assert_rename_conversation_200,
)


FAKE_BEARER_TOKEN = "fake-chat-test-token"


def _auth_headers():
    return {"Authorization": f"Bearer {FAKE_BEARER_TOKEN}"}


def _rename_url(conversation_id: str = "conv_abc") -> str:
    return f"/chat/conversations/{conversation_id}/name"


# ──────────────────────────────────────────────
# Tests: Authentication
# ──────────────────────────────────────────────

class TestRenameConversationAuth:
    """Verify authentication gates on the rename conversation endpoint."""

    async def test_missing_auth_header_returns_422(self, client):
        """No Authorization header → 422."""
        resp = await client.post(
            _rename_url(),
            json={"name": "New Name"},
        )
        assert resp.status_code == 422

    async def test_invalid_bearer_token_returns_401(self, client, mock_db, mock_redis):
        """Invalid token → 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        resp = await client.post(
            _rename_url(),
            json={"name": "New Name"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 401
        assert_message_response(resp.json(), "Invalid or expired token")


# ──────────────────────────────────────────────
# Tests: Validation
# ──────────────────────────────────────────────

class TestRenameConversationValidation:
    """Verify request body validation."""

    async def test_missing_name_returns_422(self, client, mock_redis):
        """Missing required 'name' field → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.post(
            _rename_url(),
            json={},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    async def test_empty_name_returns_422(self, client, mock_redis):
        """Empty string name → 422 (min_length=1)."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.post(
            _rename_url(),
            json={"name": ""},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    async def test_name_too_long_returns_422(self, client, mock_redis):
        """Name exceeding 255 chars → 422 (max_length=255)."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.post(
            _rename_url(),
            json={"name": "x" * 256},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422


# ──────────────────────────────────────────────
# Tests: Happy path
# ──────────────────────────────────────────────

class TestRenameConversationSuccess:
    """Verify successful conversation rename."""

    async def test_rename_returns_success(self, client, mock_redis):
        """Valid rename request → 200 with result='success'."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.rename_dify_conversation",
            new_callable=AsyncMock,
            return_value={"result": "success"},
        ):
            resp = await client.post(
                _rename_url(),
                json={"name": "New Chat Title"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert_rename_conversation_200(resp.json())

    async def test_passes_correct_params_to_service(self, client, mock_redis):
        """Verify conversation_id, name, and user are forwarded correctly."""
        mock_redis.hgetall.return_value = {"user_id": "42", "user_agent": "pytest"}

        captured_kwargs = {}

        async def _capture_rename(**kwargs):
            captured_kwargs.update(kwargs)
            return {"result": "success"}

        with patch(
            "src.routers.chat.rename_dify_conversation",
            side_effect=_capture_rename,
        ):
            resp = await client.post(
                _rename_url("c91daa90-262c-4e0a-b066-a2a2e295f81b"),
                json={"name": "Updated Title"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert captured_kwargs["conversation_id"] == "c91daa90-262c-4e0a-b066-a2a2e295f81b"
        assert captured_kwargs["name"] == "Updated Title"
        assert captured_kwargs["user"] == "42"

    async def test_name_at_max_length_accepted(self, client, mock_redis):
        """Name exactly 255 chars → 200."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.rename_dify_conversation",
            new_callable=AsyncMock,
            return_value={"result": "success"},
        ):
            resp = await client.post(
                _rename_url(),
                json={"name": "a" * 255},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert_rename_conversation_200(resp.json())


# ──────────────────────────────────────────────
# Tests: Error handling
# ──────────────────────────────────────────────

class TestRenameConversationErrors:
    """Verify error handling for the rename conversation endpoint."""

    async def test_dify_404_returns_404(self, client, mock_redis):
        """Dify conversation not found → 404."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.rename_dify_conversation",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(404, b"Not Found"),
        ):
            resp = await client.post(
                _rename_url("nonexistent_conv"),
                json={"name": "New Name"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 404
        assert_message_response(resp.json(), "Conversation not found")

    async def test_dify_502_returns_502(self, client, mock_redis):
        """Dify upstream error → 502."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.rename_dify_conversation",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(502, b"Bad Gateway"),
        ):
            resp = await client.post(
                _rename_url(),
                json={"name": "New Name"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 502
        assert_message_response(resp.json(), "Dify service unavailable")

    async def test_dify_config_error_returns_502(self, client, mock_redis):
        """Dify config missing (status_code=0) → 502."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.rename_dify_conversation",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(0, b"DIFY_API_KEY is not set"),
        ):
            resp = await client.post(
                _rename_url(),
                json={"name": "New Name"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 502
        assert_message_response(resp.json(), "Dify service unavailable")

    async def test_unexpected_exception_returns_500(self, client, mock_redis):
        """Unexpected runtime error → 500."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.rename_dify_conversation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("something broke"),
        ):
            resp = await client.post(
                _rename_url(),
                json={"name": "New Name"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 500
        assert_message_response(resp.json(), "Internal server error")
