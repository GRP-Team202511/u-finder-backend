# This code was completed by GRP Team 2025.11.
import pytest
import respx
import httpx
import json
import uuid
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock
from src.config.settings import get_settings

settings = get_settings()
DIFY_BASE_URL = settings.dify_api_base_url.rstrip("/")

@pytest.mark.asyncio
async def test_workflow_15_dify_integration_deep(integration_client: AsyncClient):
    """
    Test 15: Deep LLM/Dify Integration
    Instead of mocking the service functions, we mock the HTTP layer (respx)
    to test the actual HTTP payload parsing, Stream generation, and Error handling inside dify_service.py.
    """
    # 1. Register & Login
    unique_suffix = str(uuid.uuid4())[:8]
    user_email = f"dify_{unique_suffix}@example.com"
    password = "D1fyPassword#"
    
    captured_code = []

    async def mock_send_email(to_email, verification_code, **kwargs):
        captured_code.append(verification_code)
        return True

    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup = await integration_client.post("/auth/signup", json={"email": user_email, "password": password, "name": "DifyUser"})
        temp_token = res_signup.json()["temp_token"]
        assert len(captured_code) == 1

        res_verify = await integration_client.post(
            "/auth/verify",
            json={"code": captured_code[0]},
            headers={"temp-token": temp_token}
        )
        assert res_verify.status_code == 201

    res_login = await integration_client.post("/auth/login", json={"email": user_email, "password": password})
    assert res_login.status_code == 200
    token = res_login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Respx Mocking Dify HTTP target
    with respx.mock(assert_all_called=False) as respx_mock, patch("src.services.dify_service.settings.dify_api_key", "mocked_key"):
        # 2a. Test fetching conversations
        dify_list_route = respx_mock.get(f"{DIFY_BASE_URL}/conversations").respond(
            status_code=200,
            json={
                "data": [
                    {
                        "id": "conv-123",
                        "name": "Test Conv",
                        "status": "normal",
                        "created_at": 1700000000,
                        "updated_at": 1700000000
                    }
                ],
                "has_more": False,
                "limit": 20
            }
        )
        res_conv = await integration_client.get("/chat/conversations", headers=headers)
        assert res_conv.status_code == 200
        assert len(res_conv.json()["data"]) == 1
        assert res_conv.json()["data"][0]["id"] == "conv-123"

        # 2b. Test Chat streaming successfully
        # Mock SSE response
        sse_payload = 'data: {"event": "message", "answer": "Hello LLM!"}\n\n'
        dify_chat_route = respx_mock.post(f"{DIFY_BASE_URL}/chat-messages").respond(
            status_code=200,
            content=sse_payload.encode("utf-8"),
            headers={"Content-Type": "text/event-stream"}
        )

        res_stream = await integration_client.post(
            "/chat/messages?conversation_id=",
            headers=headers,
            json={"message": "Hi Dify"}
        )
        
        assert res_stream.status_code == 200
        assert "Hello LLM!" in res_stream.text

        # 2c. Test Dify 500 Error
        dify_err_route = respx_mock.post(f"{DIFY_BASE_URL}/chat-messages").respond(
            status_code=500,
            json={"code": "internal_error", "message": "Dify is down"}
        )
        
        res_stream_err = await integration_client.post(
            "/chat/messages?conversation_id=",
            headers=headers,
            json={"message": "Make it crash"}
        )
        # Should gracefully return error stream or error response depending on logic
        assert res_stream_err.status_code in [200, 500, 502, 503, 504]
        if res_stream_err.status_code == 200:
            assert "error" in res_stream_err.text.lower() or "500" in res_stream_err.text
