"""
Router tests for GET /chat/messages (Get Conversation History Messages).

OpenAPI contract reference: get_conversation_history.openapi.json
Endpoint behaviour:
  - Authenticates via Bearer token (Redis cache → DB fallback).
  - Forwards conversationId / first_id / limit to get_dify_messages().
  - Returns {limit: int, has_more: bool, data: list[message]}.
  - Errors from Dify → 502; unexpected exceptions → 500.
  - OpenAPI documents 400 for empty conversationId, but the backend currently
    passes it through to Dify. test_empty_conversation_id_returns_400 tracks this
    as a failing test until the backend adds explicit 400 validation.
"""
from unittest.mock import patch, AsyncMock

from tests.routers.utils.response_asserts import (
    assert_message_response,
    assert_validation_error,
    assert_chat_messages_200,
)
from src.services.dify_service import DifyUpstreamError


FAKE_BEARER_TOKEN = "fake-chat-test-token"


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {FAKE_BEARER_TOKEN}"}


# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

SAMPLE_MESSAGE = {
    "id": "msg_001",
    "conversation_id": "conv_abc",
    "inputs": {},
    "query": "Which universities should I apply to?",
    "answer": "Based on your profile, I recommend ...",
    "message_files": [],
    "feedback": None,
    "retriever_resources": [],
    "created_at": 1705395332,
    "agent_thoughts": [],
}

SAMPLE_MESSAGES_RESPONSE = {
    "limit": 20,
    "has_more": False,
    "data": [SAMPLE_MESSAGE],
}


# ===========================================================================
# Tests: Authentication
# ===========================================================================


class TestGetMessagesAuth:
    """Verify authentication gates on GET /chat/messages."""

    async def test_missing_auth_header_returns_422(self, client):
        """No Authorization header → 422 (FastAPI request validation)."""
        resp = await client.get(
            "/chat/messages",
            params={"conversationId": "conv_abc"},
        )
        assert resp.status_code == 422

    async def test_invalid_bearer_token_returns_401(self, client, mock_db, mock_redis):
        """Invalid / expired token → 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        resp = await client.get(
            "/chat/messages",
            params={"conversationId": "conv_abc"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 401
        assert_message_response(resp.json(), "Invalid or expired token")


# ===========================================================================
# Tests: Query parameter validation
# ===========================================================================


class TestGetMessagesValidation:
    """Verify FastAPI query parameter validation (422 responses)."""

    async def test_missing_conversation_id_returns_422(self, client, mock_redis):
        """Required conversationId omitted → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.get("/chat/messages", headers=_auth_headers())
        assert resp.status_code == 422
        assert_validation_error(resp.json())

    async def test_limit_below_minimum_returns_422(self, client, mock_redis):
        """limit=0 violates ge=1 constraint → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.get(
            "/chat/messages",
            params={"conversationId": "conv_abc", "limit": 0},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422
        assert_validation_error(resp.json())

    async def test_limit_above_maximum_returns_422(self, client, mock_redis):
        """limit=101 violates le=100 constraint → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.get(
            "/chat/messages",
            params={"conversationId": "conv_abc", "limit": 101},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422
        assert_validation_error(resp.json())

    async def test_limit_non_integer_returns_422(self, client, mock_redis):
        """limit='abc' cannot be coerced to int → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.get(
            "/chat/messages",
            params={"conversationId": "conv_abc", "limit": "abc"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422
        assert_validation_error(resp.json())


# ===========================================================================
# Tests: Successful responses
# ===========================================================================


class TestGetMessagesSuccess:
    """Verify 200 responses and correct parameter forwarding."""

    async def test_minimal_request_returns_200(self, client, mock_redis):
        """Only required conversationId provided → 200 with valid schema."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.get_dify_messages",
            new_callable=AsyncMock,
            return_value=SAMPLE_MESSAGES_RESPONSE,
        ):
            resp = await client.get(
                "/chat/messages",
                params={"conversationId": "conv_abc"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert_chat_messages_200(resp.json())

    async def test_correct_params_forwarded_to_service(self, client, mock_redis):
        """conversationId, first_id, limit and user are forwarded correctly."""
        mock_redis.hgetall.return_value = {"user_id": "42", "user_agent": "pytest"}

        captured = {}

        async def _capture(**kwargs):
            captured.update(kwargs)
            return SAMPLE_MESSAGES_RESPONSE

        with patch("src.routers.chat.get_dify_messages", side_effect=_capture):
            resp = await client.get(
                "/chat/messages",
                params={
                    "conversationId": "conv_xyz",
                    "first_id": "msg_050",
                    "limit": 10,
                },
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert captured["conversation_id"] == "conv_xyz"
        assert captured["first_id"] == "msg_050"
        assert captured["limit"] == 10
        assert captured["user"] == "42"

    async def test_custom_limit_reflected_in_response(self, client, mock_redis):
        """limit=5 in request → response.limit equals 5."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.get_dify_messages",
            new_callable=AsyncMock,
            return_value={"limit": 5, "has_more": True, "data": []},
        ):
            resp = await client.get(
                "/chat/messages",
                params={"conversationId": "conv_abc", "limit": 5},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["limit"] == 5

    async def test_message_item_fields_present(self, client, mock_redis):
        """When data list is non-empty, each item contains required fields."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.get_dify_messages",
            new_callable=AsyncMock,
            return_value=SAMPLE_MESSAGES_RESPONSE,
        ):
            resp = await client.get(
                "/chat/messages",
                params={"conversationId": "conv_abc"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        required_fields = {"id", "conversation_id", "query", "answer", "created_at"}
        for item in data:
            assert required_fields.issubset(item.keys()), (
                f"Message item missing fields: {required_fields - item.keys()}"
            )

    async def test_empty_data_list_is_valid(self, client, mock_redis):
        """has_more=False with empty data list is a valid 200 response."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.get_dify_messages",
            new_callable=AsyncMock,
            return_value={"limit": 20, "has_more": False, "data": []},
        ):
            resp = await client.get(
                "/chat/messages",
                params={"conversationId": "conv_empty"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        payload = resp.json()
        assert_chat_messages_200(payload)
        assert payload["data"] == []
        assert payload["has_more"] is False


# ===========================================================================
# Tests: Error handling
# ===========================================================================


class TestGetMessagesErrors:
    """Verify error responses when upstream or server fails."""

    async def test_dify_upstream_error_returns_502(self, client, mock_redis):
        """DifyUpstreamError raised by service → 502."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.get_dify_messages",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(502, b"Bad Gateway"),
        ):
            resp = await client.get(
                "/chat/messages",
                params={"conversationId": "conv_abc"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 502
        assert_message_response(resp.json(), "Dify service unavailable")

    async def test_unexpected_exception_returns_500(self, client, mock_redis):
        """Unhandled exception in service → 500."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.get_dify_messages",
            new_callable=AsyncMock,
            side_effect=RuntimeError("database exploded"),
        ):
            resp = await client.get(
                "/chat/messages",
                params={"conversationId": "conv_abc"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 500
        assert_message_response(resp.json(), "Internal server error")

    async def test_empty_conversation_id_returns_400(self, client, mock_redis):
        """OpenAPI doc mandates 400 for empty conversationId.
        Backend currently returns 200 (passes empty string to Dify) — backend fix required."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        # Patch get_dify_messages to avoid real upstream/config-dependent behavior.
        # The test must fail specifically because the backend does not return 400
        # for empty conversationId, not because of a missing API key or network call.
        with patch(
            "src.routers.chat.get_dify_messages",
            new_callable=AsyncMock,
            return_value={"limit": 20, "has_more": False, "data": []},
        ):
            resp = await client.get(
                "/chat/messages",
                params={"conversationId": ""},
                headers=_auth_headers(),
            )
        assert resp.status_code == 400
