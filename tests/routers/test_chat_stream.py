"""
Router tests for POST /chat/{conversation_id}
"""
import json
from unittest.mock import patch

from tests.routers.utils.response_asserts import (
    assert_message_response,
    assert_stream_error_event,
    assert_validation_error,
)


FAKE_BEARER_TOKEN = "fake-chat-test-token"


def _auth_headers():
    return {"Authorization": f"Bearer {FAKE_BEARER_TOKEN}"}


SAMPLE_AGENT_THOUGHT = {
    "event": "agent_thought",
    "id": "thought_1",
    "task_id": "task_abc",
    "message_id": "msg_abc",
    "conversation_id": "conv_abc",
    "position": 1,
    "thought": "Searching for universities...",
    "tool": "search",
    "tool_input": "{}",
    "created_at": 1705395332,
}

SAMPLE_AGENT_MESSAGE = {
    "event": "agent_message",
    "task_id": "task_abc",
    "message_id": "msg_abc",
    "conversation_id": "conv_abc",
    "answer": "Based on your profile, ",
    "created_at": 1705395333,
}

SAMPLE_MESSAGE_END = {
    "event": "message_end",
    "task_id": "task_abc",
    "message_id": "msg_abc",
    "conversation_id": "conv_abc",
    "metadata": {"usage": {"total_tokens": 120, "latency": 1.8}},
}


# ──────────────────────────────────────────────
# Tests: Authentication
# ──────────────────────────────────────────────

class TestChatAuth:
    """Verify authentication gates on the chat endpoint."""

    async def test_missing_auth_header_returns_422(self, client):
        """No Authorization header → 422 (FastAPI validation)."""
        resp = await client.post("/chat/null", json={"message": "hi"})
        assert resp.status_code == 422

    async def test_invalid_bearer_token_returns_401(self, client, mock_db, mock_redis):
        """Invalid token → 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        resp = await client.post(
            "/chat/null",
            json={"message": "hi"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 401
        assert_message_response(resp.json(), "Invalid or expired token")


# ──────────────────────────────────────────────
# Tests: Validation
# ──────────────────────────────────────────────

class TestChatValidation:
    """Request body validation."""

    async def test_empty_message_returns_422(self, client, mock_redis):
        """Empty string message → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.post(
            "/chat/null",
            json={"message": ""},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422
        assert_validation_error(resp.json())

    async def test_missing_message_returns_422(self, client, mock_redis):
        """Missing message field → 422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        resp = await client.post(
            "/chat/null",
            json={},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422
        assert_validation_error(resp.json())


# ──────────────────────────────────────────────
# Tests: SSE Streaming (happy path)
# ──────────────────────────────────────────────

class TestChatStream:
    """Verify the SSE streaming behaviour with a mocked Dify backend."""

    async def test_successful_stream(self, client, mock_redis):
        """Full SSE flow: agent_thought → agent_message → message_end."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        async def _fake_stream(**kwargs):
            for evt in [SAMPLE_AGENT_THOUGHT, SAMPLE_AGENT_MESSAGE, SAMPLE_MESSAGE_END]:
                yield f"data: {json.dumps(evt)}\n\n"

        with patch(
            "src.routers.chat.stream_dify_chat",
            side_effect=lambda **kw: _fake_stream(**kw),
        ):
            resp = await client.post(
                "/chat/conv_abc",
                json={"message": "推荐英国大学"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        # Parse SSE frames from the response body
        body = resp.text
        frames = [
            line[len("data: "):]
            for line in body.strip().split("\n")
            if line.startswith("data: ")
        ]
        assert len(frames) == 3

        thought = json.loads(frames[0])
        assert thought["event"] == "agent_thought"
        assert thought["conversation_id"] == "conv_abc"

        message = json.loads(frames[1])
        assert message["event"] == "agent_message"
        assert message["answer"] == "Based on your profile, "

        end = json.loads(frames[2])
        assert end["event"] == "message_end"
        assert end["metadata"]["usage"]["total_tokens"] == 120

    async def test_new_conversation_null_id(self, client, mock_redis):
        """conversation_id='null' should be treated as a new conversation."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        captured_kwargs = {}

        async def _fake_stream(**kwargs):
            captured_kwargs.update(kwargs)
            yield f"data: {json.dumps(SAMPLE_MESSAGE_END)}\n\n"

        with patch(
            "src.routers.chat.stream_dify_chat",
            side_effect=lambda **kw: _fake_stream(**kw),
        ):
            resp = await client.post(
                "/chat/null",
                json={"message": "hello"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        # conversation_id should be None (not the literal string "null")
        assert captured_kwargs.get("conversation_id") is None


# ──────────────────────────────────────────────
# Tests: Error handling
# ──────────────────────────────────────────────

class TestChatErrors:
    """Verify error handling when Dify is unavailable."""

    async def test_dify_upstream_error_sends_error_event(self, client, mock_redis):
        """DifyUpstreamError should produce an SSE error frame (not crash)."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        from src.services.dify_service import DifyUpstreamError

        async def _failing_stream(**kwargs):
            raise DifyUpstreamError(502, b"Bad Gateway")
            # Make this a generator
            yield  # pragma: no cover

        with patch(
            "src.routers.chat.stream_dify_chat",
            side_effect=lambda **kw: _failing_stream(**kw),
        ):
            resp = await client.post(
                "/chat/null",
                json={"message": "test"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200  # SSE stream opened
        body = resp.text
        frames = [
            line[len("data: "):]
            for line in body.strip().split("\n")
            if line.startswith("data: ")
        ]
        assert len(frames) >= 1
        error_evt = json.loads(frames[0])
        assert_stream_error_event(error_evt)
        assert "unavailable" in error_evt["message"].lower()

    async def test_unexpected_error_sends_error_event(self, client, mock_redis):
        """Unexpected exceptions should produce an SSE error frame."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        async def _crashing_stream(**kwargs):
            raise RuntimeError("Something unexpected")
            yield  # pragma: no cover

        with patch(
            "src.routers.chat.stream_dify_chat",
            side_effect=lambda **kw: _crashing_stream(**kw),
        ):
            resp = await client.post(
                "/chat/null",
                json={"message": "test"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        body = resp.text
        frames = [
            line[len("data: "):]
            for line in body.strip().split("\n")
            if line.startswith("data: ")
        ]
        assert len(frames) >= 1
        error_evt = json.loads(frames[0])
        assert_stream_error_event(error_evt)

    async def test_dify_timeout_sends_error_event(self, client, mock_redis):
        """504 Gateway Timeout from Dify should produce an SSE error frame."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        from src.services.dify_service import DifyUpstreamError

        async def _timeout_stream(**kwargs):
            raise DifyUpstreamError(504, b"Gateway Timeout")
            yield  # pragma: no cover

        with patch(
            "src.routers.chat.stream_dify_chat",
            side_effect=lambda **kw: _timeout_stream(**kw),
        ):
            resp = await client.post(
                "/chat/null",
                json={"message": "test"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200  # SSE stream always opens with 200
        frames = [
            line[len("data: "):]
            for line in resp.text.strip().split("\n")
            if line.startswith("data: ")
        ]
        assert len(frames) >= 1
        error_evt = json.loads(frames[0])
        assert_stream_error_event(error_evt)
        assert "unavailable" in error_evt["message"].lower()


