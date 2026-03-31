# This code was completed by GRP Team 2025.11.
"""
Integration tests for Chat Workflows (Conversations, Messages, Dify).
"""
import pytest
import json
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_workflow_06_chat_flow(integration_client: AsyncClient):
    # 1. Signup and Login
    sent_codes = []
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup = await integration_client.post("/auth/signup", json={
            "email": "chat_user@example.com",
            "name": "Chat User",
            "password": "Password123"
        })
        assert res_signup.status_code == 200
        temp_token = res_signup.json().get("temp_token")

        await integration_client.post(
            "/auth/verify",
            json={"code": sent_codes[0]},
            headers={"temp-token": temp_token}
        )

    res_login = await integration_client.post("/auth/login", json={
        "email": "chat_user@example.com",
        "password": "Password123"
    })
    token = res_login.json().get("token")
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Get Conversations (Empty initially)
    # mock Dify response
    with patch("src.routers.chat.get_dify_conversations", return_value={"data": [], "has_more": False, "limit": 20}):
        res_conv = await integration_client.get("/chat/conversations", headers=headers)
        assert res_conv.status_code == 200
        assert res_conv.json()["data"] == []

    # 3. Chat stream (Creating a new conversation)
    async def mock_chat_stream(*args, **kwargs):
        yield json.dumps({"event": "message", "answer": "Hello from Dify!"}) + "\n"

    with patch("src.routers.chat.stream_dify_chat", new=mock_chat_stream):
        res_stream = await integration_client.post(
            "/chat/messages?conversation_id=",
            headers=headers,
            json={
                "message": "Hello"
            }
        )
        assert res_stream.status_code == 200
        content = res_stream.text
        assert "Hello from Dify!" in content

    # 4. Message feedback
    with patch("src.routers.chat.submit_dify_feedback", return_value={"result": "success"}):
        res_feedback = await integration_client.post(
            "/chat/messages/msg-123/feedbacks",
            headers=headers,
            json={"rating": "like"}
        )
        assert res_feedback.status_code == 200

    # 5. Rename conversation
    with patch("src.routers.chat.rename_dify_conversation", new_callable=AsyncMock, return_value={"result": "success"}):
        res_rename = await integration_client.post(
            "/chat/conversations/conv-123/name",
            headers=headers,
            json={"name": "New Name"}
        )
        assert res_rename.status_code == 200
        assert res_rename.json().get("result") == "success"

    # 6. Delete conversation
    with patch("src.routers.chat.delete_dify_conversation", return_value={"result": "success"}):
        res_delete = await integration_client.delete(
            "/chat/conversations/conv-123",
            headers=headers
        )
        assert res_delete.status_code == 200

    # 7. Stop chat text generation
    with patch("src.routers.chat.stop_dify_chat", return_value={"result": "success"}):
        res_stop = await integration_client.post(
            "/chat/task-123/stop",
            headers=headers
        )
        assert res_stop.status_code == 200
        assert res_stop.json().get("result") == "success"
