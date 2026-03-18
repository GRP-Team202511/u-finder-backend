"""
Integration tests for Authentication Flows.
Tests run against REAL Database and Redis connections but with strict Rollback isolations.
"""
import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from unittest.mock import patch, AsyncMock

# ──────────────────────────────────────────────────────────────────────────────
# WORKFLOW 1: Standard User Lifecycle (Signup -> Verify -> Login -> Fetch Profile)
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_workflow_01_standard_user_lifecycle(integration_client: AsyncClient, real_redis: Redis):
    # Mock email sending so we don't actually spam emails, and capture the code
    sent_codes = []
    
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        # 1. Signup
        signup_payload = {
            "email": "lifecycle_test@example.com",
            "name": "Lifecycle Test",
            "password": "Password123"
        }
        
        res_signup = await integration_client.post("/auth/signup", json=signup_payload)
        assert res_signup.status_code == 200, res_signup.text
        temp_token = res_signup.json().get("temp_token")
        assert temp_token is not None
        
        # Verify email was captured
        assert len(sent_codes) == 1
        verification_code = sent_codes[0]

        # 2. Verify Signup
        verify_payload = {
            "code": verification_code
        }
        res_verify = await integration_client.post(
            "/auth/verify", 
            json=verify_payload,
            headers={"temp-token": temp_token}
        )
        assert res_verify.status_code == 201, res_verify.text
        
        # 3. Login
        login_payload = {
            "email": "lifecycle_test@example.com",
            "password": "Password123"
        }
        res_login = await integration_client.post("/auth/login", json=login_payload)
        assert res_login.status_code == 200, res_login.text
        session_token = res_login.json().get("token")
        assert session_token is not None
        
        # 4. Access Account Info
        res_info = await integration_client.get(
            "/auth/settings/info",
            headers={"Authorization": f"Bearer {session_token}"}
        )
        assert res_info.status_code == 200, res_info.text
        assert res_info.json().get("name") == "Lifecycle Test"

        # Access Profile
        res_profile = await integration_client.get(
            "/profile/personal",
            headers={"Authorization": f"Bearer {session_token}"}
        )
        assert res_profile.status_code == 200, res_profile.text
        # 5. Logout
        logout_payload = {"session_token": session_token}
        res_logout = await integration_client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {session_token}"},
            json=logout_payload
        )
        assert res_logout.status_code == 200, res_logout.text
