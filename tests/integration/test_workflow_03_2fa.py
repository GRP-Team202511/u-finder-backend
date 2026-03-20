"""
Integration tests for 2FA Flow.
"""
import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from unittest.mock import patch
import json

@pytest.mark.asyncio
async def test_workflow_03_2fa_lifecycle(integration_client: AsyncClient, real_redis: Redis):
    # 1. Signup a user 
    sent_codes = []
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup = await integration_client.post("/auth/signup", json={
            "email": "2fa_test@example.com",
            "name": "2FA Test",
            "password": "Password123"
        })
        assert res_signup.status_code == 200
        temp_token = res_signup.json().get("temp_token")
        
        # Verify
        res_verify = await integration_client.post(
            "/auth/verify", 
            json={"code": sent_codes[0]}, 
            headers={"temp-token": temp_token}
        )
        assert res_verify.status_code == 201

    # 2. Login
    res_login = await integration_client.post("/auth/login", json={
        "email": "2fa_test@example.com",
        "password": "Password123"
    })
    assert res_login.status_code == 200
    session_token = res_login.json().get("token")

    # 3. Setup 2FA
    res_setup = await integration_client.post(
        "/auth/2fa/setup",
        headers={"Authorization": f"Bearer {session_token}"}
    )
    assert res_setup.status_code == 200

    # 4. Confirm 2FA (Mocking verify_totp_code)
    with patch("src.routers.two_factor.verify_totp_code", return_value=True):
        res_confirm = await integration_client.post(
            "/auth/2fa/confirm",
            json={"code": "123456"},
            headers={"Authorization": f"Bearer {session_token}"}
        )
        assert res_confirm.status_code == 200

    # 5. Logout
    await integration_client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"session_token": session_token}
    )

    # 6. Login again -> should prompt for 2FA (202 Accepted)
    res_login_2fa = await integration_client.post("/auth/login", json={
        "email": "2fa_test@example.com",
        "password": "Password123"
    })
    assert res_login_2fa.status_code == 202
    res_login_2fa_data = res_login_2fa.json()
    temp_token_2fa = res_login_2fa_data.get("temp_token")
    assert temp_token_2fa is not None

    # 7. Verify 2FA
    with patch("src.routers.two_factor.verify_totp_code", return_value=True):
        res_verify_2fa = await integration_client.post(
            "/auth/2fa/verify",
            json={"code": "654321"},
            headers={"Temp-Token": temp_token_2fa}
        )
        assert res_verify_2fa.status_code == 200, res_verify_2fa.text
        new_session_token = res_verify_2fa.json().get("token")
        assert new_session_token is not None

    # 8. Disable 2FA
    res_disable = await integration_client.post(
        "/auth/2fa/disable",
        json={"password": "Password123"},
        headers={"Authorization": f"Bearer {new_session_token}"}
    )
    assert res_disable.status_code == 200
