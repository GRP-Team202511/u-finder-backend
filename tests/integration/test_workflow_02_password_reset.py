# This code was completed by GRP Team 2025.11.
"""
Integration tests for Password Reset Flow.
"""
import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from unittest.mock import patch

@pytest.mark.asyncio
async def test_workflow_02_password_reset(integration_client: AsyncClient, real_redis: Redis):
    # 1. Signup a user first to have an account to reset
    sent_codes = []
    
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        # 1. Signup
        signup_payload = {
            "email": "reset_test@example.com",
            "name": "Reset Test",
            "password": "OldPassword123"
        }
        res_signup = await integration_client.post("/auth/signup", json=signup_payload)
        assert res_signup.status_code == 200
        temp_token = res_signup.json().get("temp_token")
        
        # Verify
        verify_payload = {"code": sent_codes[0]}
        res_verify = await integration_client.post("/auth/verify", json=verify_payload, headers={"temp-token": temp_token})
        assert res_verify.status_code == 201

    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        # Clear sent codes
        sent_codes.clear()

        # 2. Request Password Reset
        reset_request_payload = {"email": "reset_test@example.com"}
        res_reset_req = await integration_client.post("/auth/reset", json=reset_request_payload)
        assert res_reset_req.status_code == 200
        reset_temp_token = res_reset_req.json().get("temp_token")
        assert reset_temp_token is not None
        assert len(sent_codes) == 1
        reset_code = sent_codes[0]

        # 3. Verify Reset Code
        res_reset_verify = await integration_client.post(
            "/auth/verify-reset-code",
            json={"code": reset_code},
            headers={"temp_token": reset_temp_token}
        )
        assert res_reset_verify.status_code == 200, res_reset_verify.text
        
        # 4. Confirm Reset Password
        res_confirm = await integration_client.post(
            "/auth/confirm-reset-password",
            json={"code": reset_code, "newPassword": "NewPassword456"},
            headers={"temp_token": reset_temp_token}
        )
        assert res_confirm.status_code == 200, res_confirm.text

        # 5. Login with New Password
        login_new_payload = {
            "email": "reset_test@example.com",
            "password": "NewPassword456"
        }
        res_login_new = await integration_client.post("/auth/login", json=login_new_payload)
        assert res_login_new.status_code == 200
        
        # 6. Check Old Password Fails
        login_old_payload = {
            "email": "reset_test@example.com",
            "password": "OldPassword123"
        }
        res_login_old = await integration_client.post("/auth/login", json=login_old_payload)
        assert res_login_old.status_code in [400, 401]
