"""
Router tests for POST /chat/{task_id}/stop
"""
from unittest.mock import patch, AsyncMock

from src.services.dify_service import DifyUpstreamError
from tests.routers.utils.response_asserts import (
    assert_message_response,
    assert_stop_chat_200,
)


FAKE_BEARER_TOKEN = "fake-chat-test-token"


def _auth_headers():
    return {"Authorization": f"Bearer {FAKE_BEARER_TOKEN}"}


# ──────────────────────────────────────────────
# Tests: Authentication
# ──────────────────────────────────────────────

class TestStopChatAuth:
    """Verify authentication gates on the stop endpoint."""

    async def test_missing_auth_header_returns_422(self, client):
        """No Authorization header → 422."""
        resp = await client.post("/chat/task_abc/stop")
        assert resp.status_code == 422

    async def test_invalid_bearer_token_returns_401(self, client, mock_db, mock_redis):
        """Invalid token → 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        resp = await client.post(
            "/chat/task_abc/stop",
            headers=_auth_headers(),
        )
        assert resp.status_code == 401
        assert_message_response(resp.json(), "Invalid or expired token")


# ──────────────────────────────────────────────
# Tests: Happy path
# ──────────────────────────────────────────────

class TestStopChatSuccess:
    """Verify successful stop generation."""

    async def test_stop_returns_success(self, client, mock_redis):
        """Valid stop request → 200 with result='success'."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.stop_dify_chat",
            new_callable=AsyncMock,
            return_value={"result": "success"},
        ):
            resp = await client.post(
                "/chat/task_abc/stop",
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert_stop_chat_200(resp.json())

    async def test_stop_passes_correct_params(self, client, mock_redis):
        """Verify task_id and user are forwarded correctly to the service."""
        mock_redis.hgetall.return_value = {"user_id": "42", "user_agent": "pytest"}

        captured_kwargs = {}

        async def _capture_stop(**kwargs):
            captured_kwargs.update(kwargs)
            return {"result": "success"}

        with patch(
            "src.routers.chat.stop_dify_chat",
            side_effect=_capture_stop,
        ):
            resp = await client.post(
                "/chat/task_xyz/stop",
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert captured_kwargs["task_id"] == "task_xyz"
        assert captured_kwargs["user"] == "42"


# ──────────────────────────────────────────────
# Tests: Error handling
# ──────────────────────────────────────────────

class TestStopChatErrors:
    """Verify error handling for the stop endpoint."""

    async def test_dify_404_returns_404(self, client, mock_redis):
        """Dify task not found → 404."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.stop_dify_chat",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(404, b"Not Found"),
        ):
            resp = await client.post(
                "/chat/task_nonexistent/stop",
                headers=_auth_headers(),
            )

        assert resp.status_code == 404
        assert_message_response(resp.json(), "Task not found or already completed")

    async def test_dify_502_returns_502(self, client, mock_redis):
        """Dify upstream error → 502."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.stop_dify_chat",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(502, b"Bad Gateway"),
        ):
            resp = await client.post(
                "/chat/task_abc/stop",
                headers=_auth_headers(),
            )

        assert resp.status_code == 502
        assert_message_response(resp.json(), "Dify service unavailable")

    async def test_dify_config_error_returns_502(self, client, mock_redis):
        """Dify config missing (status_code=0) → 502."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.stop_dify_chat",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(0, b"DIFY_API_KEY is not set"),
        ):
            resp = await client.post(
                "/chat/task_abc/stop",
                headers=_auth_headers(),
            )

        assert resp.status_code == 502
        assert_message_response(resp.json(), "Dify service unavailable")
