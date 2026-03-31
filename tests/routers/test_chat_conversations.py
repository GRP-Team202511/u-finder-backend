# This code was completed by GRP Team 2025.11.
"""
Router tests for GET /chat/conversations
"""
from unittest.mock import patch, AsyncMock

from src.services.dify_service import DifyUpstreamError
from tests.routers.utils.response_asserts import (
    assert_message_response,
    assert_conversations_200,
)


FAKE_BEARER_TOKEN = "fake-chat-test-token"

FAKE_CONVERSATIONS_RESPONSE = {
    "limit": 20,
    "has_more": False,
    "data": [
        {
            "id": "conv-aaa-111",
            "name": "New chat",
            "inputs": {},
            "status": "normal",
            "introduction": "",
            "created_at": 1679667915,
            "updated_at": 1679667915,
        },
        {
            "id": "conv-bbb-222",
            "name": "How to apply for MIT",
            "inputs": {"book": "book"},
            "status": "normal",
            "introduction": "",
            "created_at": 1679667800,
            "updated_at": 1679667900,
        },
    ],
}


def _auth_headers():
    return {"Authorization": f"Bearer {FAKE_BEARER_TOKEN}"}


# ──────────────────────────────────────────────
# Tests: Authentication
# ──────────────────────────────────────────────

class TestConversationsAuth:
    """Verify authentication gates on the conversations endpoint."""

    async def test_missing_auth_header_returns_422(self, client):
        """No Authorization header → 422."""
        resp = await client.get("/chat/conversations")
        assert resp.status_code == 422

    async def test_invalid_bearer_token_returns_401(self, client, mock_db, mock_redis):
        """Invalid token → 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        resp = await client.get(
            "/chat/conversations",
            headers=_auth_headers(),
        )
        assert resp.status_code == 401
        assert_message_response(resp.json(), "Invalid or expired token")


# ──────────────────────────────────────────────
# Tests: Validation
# ──────────────────────────────────────────────

class TestConversationsValidation:
    """Verify query parameter validation."""

    async def test_limit_below_min_returns_422(self, client, mock_redis):
        """limit=0 → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.get(
            "/chat/conversations?limit=0",
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    async def test_limit_above_max_returns_422(self, client, mock_redis):
        """limit=101 → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.get(
            "/chat/conversations?limit=101",
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    async def test_limit_not_integer_returns_422(self, client, mock_redis):
        """limit=abc → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.get(
            "/chat/conversations?limit=abc",
            headers=_auth_headers(),
        )
        assert resp.status_code == 422


# ──────────────────────────────────────────────
# Tests: Happy paths
# ──────────────────────────────────────────────

class TestConversationsSuccess:
    """Verify successful conversation list retrieval."""

    async def test_default_params_returns_conversations(self, client, mock_redis):
        """Default params → 200 with conversation list."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.get_dify_conversations",
            new_callable=AsyncMock,
            return_value=FAKE_CONVERSATIONS_RESPONSE,
        ):
            resp = await client.get(
                "/chat/conversations",
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert_conversations_200(resp.json())
        assert len(resp.json()["data"]) == 2

    async def test_with_pagination_params(self, client, mock_redis):
        """Custom last_id and limit → 200."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        paginated_response = {
            "limit": 5,
            "has_more": True,
            "data": [FAKE_CONVERSATIONS_RESPONSE["data"][0]],
        }

        with patch(
            "src.routers.chat.get_dify_conversations",
            new_callable=AsyncMock,
            return_value=paginated_response,
        ):
            resp = await client.get(
                "/chat/conversations?last_id=conv-aaa-111&limit=5",
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 5
        assert data["has_more"] is True
        assert len(data["data"]) == 1

    async def test_empty_result(self, client, mock_redis):
        """No conversations → 200 with empty data list."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.get_dify_conversations",
            new_callable=AsyncMock,
            return_value={"limit": 20, "has_more": False, "data": []},
        ):
            resp = await client.get(
                "/chat/conversations",
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []
        assert data["has_more"] is False

    async def test_passes_correct_params_to_service(self, client, mock_redis):
        """Verify last_id, limit, and user are forwarded correctly."""
        mock_redis.hgetall.return_value = {"user_id": "42", "user_agent": "pytest"}

        captured_kwargs = {}

        async def _capture(**kwargs):
            captured_kwargs.update(kwargs)
            return {"limit": 10, "has_more": False, "data": []}

        with patch(
            "src.routers.chat.get_dify_conversations",
            side_effect=_capture,
        ):
            resp = await client.get(
                "/chat/conversations?last_id=conv-xyz&limit=10",
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert captured_kwargs["user"] == "42"
        assert captured_kwargs["last_id"] == "conv-xyz"
        assert captured_kwargs["limit"] == 10


# ──────────────────────────────────────────────
# Tests: Error handling
# ──────────────────────────────────────────────

class TestConversationsErrors:
    """Verify error handling for the conversations endpoint."""

    async def test_dify_502_returns_502(self, client, mock_redis):
        """Dify upstream error → 502."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.get_dify_conversations",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(502, b"Bad Gateway"),
        ):
            resp = await client.get(
                "/chat/conversations",
                headers=_auth_headers(),
            )

        assert resp.status_code == 502
        assert_message_response(resp.json(), "Dify service unavailable")

    async def test_dify_config_error_returns_502(self, client, mock_redis):
        """Dify config missing (status_code=0) → 502."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.get_dify_conversations",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(0, b"DIFY_API_KEY is not set"),
        ):
            resp = await client.get(
                "/chat/conversations",
                headers=_auth_headers(),
            )

        assert resp.status_code == 502
        assert_message_response(resp.json(), "Dify service unavailable")

    async def test_unexpected_error_returns_500(self, client, mock_redis):
        """Unexpected exception → 500."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.get_dify_conversations",
            new_callable=AsyncMock,
            side_effect=RuntimeError("something broke"),
        ):
            resp = await client.get(
                "/chat/conversations",
                headers=_auth_headers(),
            )

        assert resp.status_code == 500
        assert_message_response(resp.json(), "Internal server error")
