# This code was completed by GRP Team 2025.11.
"""
Router tests for POST /chat/messages/{message_id}/feedbacks
"""
from unittest.mock import patch, AsyncMock

from src.services.dify_service import DifyUpstreamError
from tests.routers.utils.response_asserts import (
    assert_message_response,
    assert_feedback_200,
)


FAKE_BEARER_TOKEN = "fake-chat-test-token"


def _auth_headers():
    return {"Authorization": f"Bearer {FAKE_BEARER_TOKEN}"}


def _feedback_url(message_id: str = "msg_abc") -> str:
    return f"/chat/messages/{message_id}/feedbacks"


# ──────────────────────────────────────────────
# Tests: Authentication
# ──────────────────────────────────────────────

class TestFeedbackAuth:
    """Verify authentication gates on the feedback endpoint."""

    async def test_missing_auth_header_returns_422(self, client):
        """No Authorization header → 422."""
        resp = await client.post(
            _feedback_url(),
            json={"rating": "like"},
        )
        assert resp.status_code == 422

    async def test_invalid_bearer_token_returns_401(self, client, mock_db, mock_redis):
        """Invalid token → 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        resp = await client.post(
            _feedback_url(),
            json={"rating": "like"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 401
        assert_message_response(resp.json(), "Invalid or expired token")


# ──────────────────────────────────────────────
# Tests: Validation
# ──────────────────────────────────────────────

class TestFeedbackValidation:
    """Verify request body validation."""

    async def test_missing_rating_returns_422(self, client, mock_redis):
        """Missing required 'rating' field → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.post(
            _feedback_url(),
            json={},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    async def test_invalid_rating_value_returns_422(self, client, mock_redis):
        """Invalid rating value (not like/dislike/null) → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.post(
            _feedback_url(),
            json={"rating": "love"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422


# ──────────────────────────────────────────────
# Tests: Happy paths
# ──────────────────────────────────────────────

class TestFeedbackSuccess:
    """Verify successful feedback submission."""

    async def test_like_returns_success(self, client, mock_redis):
        """Valid like feedback → 200 with result='success'."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.submit_dify_feedback",
            new_callable=AsyncMock,
            return_value={"result": "success"},
        ):
            resp = await client.post(
                _feedback_url(),
                json={"rating": "like"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert_feedback_200(resp.json())

    async def test_dislike_returns_success(self, client, mock_redis):
        """Valid dislike feedback → 200."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.submit_dify_feedback",
            new_callable=AsyncMock,
            return_value={"result": "success"},
        ):
            resp = await client.post(
                _feedback_url(),
                json={"rating": "dislike"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert_feedback_200(resp.json())

    async def test_null_rating_revokes_feedback(self, client, mock_redis):
        """null rating (revoke) → 200."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.submit_dify_feedback",
            new_callable=AsyncMock,
            return_value={"result": "success"},
        ):
            resp = await client.post(
                _feedback_url(),
                json={"rating": None},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert_feedback_200(resp.json())

    async def test_like_with_content_returns_success(self, client, mock_redis):
        """Like with content text → 200."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.submit_dify_feedback",
            new_callable=AsyncMock,
            return_value={"result": "success"},
        ):
            resp = await client.post(
                _feedback_url(),
                json={"rating": "like", "content": "Very helpful answer!"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert_feedback_200(resp.json())

    async def test_passes_correct_params_to_service(self, client, mock_redis):
        """Verify message_id, rating, user, and content are forwarded correctly."""
        mock_redis.hgetall.return_value = {"user_id": "42", "user_agent": "pytest"}

        captured_kwargs = {}

        async def _capture_feedback(**kwargs):
            captured_kwargs.update(kwargs)
            return {"result": "success"}

        with patch(
            "src.routers.chat.submit_dify_feedback",
            side_effect=_capture_feedback,
        ):
            resp = await client.post(
                _feedback_url("msg_xyz"),
                json={"rating": "dislike", "content": "Not relevant"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert captured_kwargs["message_id"] == "msg_xyz"
        assert captured_kwargs["rating"] == "dislike"
        assert captured_kwargs["user"] == "42"
        assert captured_kwargs["content"] == "Not relevant"

    async def test_null_content_not_forwarded(self, client, mock_redis):
        """When content is omitted, it should be passed as None."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        captured_kwargs = {}

        async def _capture_feedback(**kwargs):
            captured_kwargs.update(kwargs)
            return {"result": "success"}

        with patch(
            "src.routers.chat.submit_dify_feedback",
            side_effect=_capture_feedback,
        ):
            resp = await client.post(
                _feedback_url(),
                json={"rating": "like"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert captured_kwargs["content"] is None


# ──────────────────────────────────────────────
# Tests: Error handling
# ──────────────────────────────────────────────

class TestFeedbackErrors:
    """Verify error handling for the feedback endpoint."""

    async def test_dify_404_returns_404(self, client, mock_redis):
        """Dify message not found → 404."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.submit_dify_feedback",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(404, b"Not Found"),
        ):
            resp = await client.post(
                _feedback_url("msg_nonexistent"),
                json={"rating": "like"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 404
        assert_message_response(resp.json(), "Message not found")

    async def test_dify_502_returns_502(self, client, mock_redis):
        """Dify upstream error → 502."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.submit_dify_feedback",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(502, b"Bad Gateway"),
        ):
            resp = await client.post(
                _feedback_url(),
                json={"rating": "like"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 502
        assert_message_response(resp.json(), "Dify service unavailable")

    async def test_dify_config_error_returns_502(self, client, mock_redis):
        """Dify config missing (status_code=0) → 502."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.submit_dify_feedback",
            new_callable=AsyncMock,
            side_effect=DifyUpstreamError(0, b"DIFY_API_KEY is not set"),
        ):
            resp = await client.post(
                _feedback_url(),
                json={"rating": "like"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 502
        assert_message_response(resp.json(), "Dify service unavailable")

    async def test_unexpected_error_returns_500(self, client, mock_redis):
        """Unexpected exception → 500."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        with patch(
            "src.routers.chat.submit_dify_feedback",
            new_callable=AsyncMock,
            side_effect=RuntimeError("something broke"),
        ):
            resp = await client.post(
                _feedback_url(),
                json={"rating": "like"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 500
        assert_message_response(resp.json(), "Internal server error")
