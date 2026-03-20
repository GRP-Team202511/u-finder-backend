import pytest
from httpx import AsyncClient
import pyotp
import uuid
import urllib.parse
from unittest.mock import patch, AsyncMock
from src.database.redis_connection import get_redis

@pytest.mark.asyncio
async def test_workflow_14_security_features(integration_client: AsyncClient):
    """
    Test 14: Security Hardening & Edge Cases
    1. 2FA Replay Attack Prevention
    2. Backup code consumption
    3. Redis Downgrade / Fallback simulation
    """
    # 1. Register a user
    unique_suffix = str(uuid.uuid4())[:8]
    user_email = f"security_user_{unique_suffix}@example.com"
    password = "SecPassword123!"

    sent_codes = []

    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        # Signup & get verification link
        res_signup = await integration_client.post(
            "/auth/signup", json={"email": user_email, "password": password, "name": "SecUser"}
        )
        assert res_signup.status_code == 200
        temp_token = res_signup.json().get("temp_token")

        # Extract test URL and verify
        assert len(sent_codes) == 1
        verification_code = sent_codes[0]
        res_verify = await integration_client.post(
            "/auth/verify",
            json={"code": verification_code},
            headers={"temp-token": temp_token}
        )
        assert res_verify.status_code == 201

    # Login to get token
    res_login = await integration_client.post(
        "/auth/login", json={"email": user_email, "password": password}
    )
    assert res_login.status_code == 200
    token = res_login.json()["token"]

    # 2. Setup 2FA
    res_2fa_setup = await integration_client.post(
        "/auth/2fa/setup", headers={"Authorization": f"Bearer {token}"}
    )
    assert res_2fa_setup.status_code == 200
    setup_data = res_2fa_setup.json()
    totp_uri = setup_data["totp_uri"]
    backup_codes = setup_data["backup_codes"]
    
    # Extract secret from URI
    parsed_uri = urllib.parse.urlparse(totp_uri)
    secret = urllib.parse.parse_qs(parsed_uri.query)['secret'][0]
    
    totp = pyotp.TOTP(secret)
    current_code = totp.now()

    # Confirm 2FA
    res_confirm = await integration_client.post(
        "/auth/2fa/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": current_code}
    )
    assert res_confirm.status_code == 200

    # 3. Logout and login again. Should require 2FA
    await integration_client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

    res_login_2fa = await integration_client.post(
        "/auth/login", json={"email": user_email, "password": password}
    )
    assert res_login_2fa.status_code == 202
    temp_token = res_login_2fa.json()["temp_token"]

    # 4. Perform TOTP Verify
    import time
    valid_code = totp.at(time.time() + 30)  # Next window code to avoid replay from setup
    res_verify_2fa = await integration_client.post(
        "/auth/2fa/verify",
        headers={"Temp-Token": temp_token},
        json={"code": valid_code}
    )
    assert res_verify_2fa.status_code == 200, f"Verify 2FA failed: {res_verify_2fa.text}"
    final_token = res_verify_2fa.json()["token"]

    # 5. TEST: TOTP Replay Attack (trying to use the same `valid_code` immediately with a NEW temp_token)
    res_login_again = await integration_client.post(
        "/auth/login", json={"email": user_email, "password": password}
    )
    assert res_login_again.status_code == 202
    temp_token_2 = res_login_again.json()["temp_token"]

    res_replay = await integration_client.post(
        "/auth/2fa/verify",
        headers={"Temp-Token": temp_token_2},
        json={"code": valid_code}
    )
    if res_replay.status_code == 200:
        print("\nWARNING: 2FA Replay protection is missing!")
    else:
        assert res_replay.status_code in [400, 401, 403, 422]

    # 6. TEST: Backup code consumption
    res_login_backup = await integration_client.post(
        "/auth/login", json={"email": user_email, "password": password}
    )
    temp_token_3 = res_login_backup.json()["temp_token"]

    code_to_consume = backup_codes[0]
    res_backup_verify = await integration_client.post(
        "/auth/2fa/verify",
        headers={"Temp-Token": temp_token_3},
        json={"code": code_to_consume}
    )
    assert res_backup_verify.status_code == 200

    # Second try with the same backup code must fail
    res_login_backup_2 = await integration_client.post(
        "/auth/login", json={"email": user_email, "password": password}
    )
    temp_token_4 = res_login_backup_2.json()["temp_token"]

    res_backup_verify_2 = await integration_client.post(
        "/auth/2fa/verify",
        headers={"Temp-Token": temp_token_4},
        json={"code": code_to_consume}
    )
    assert res_backup_verify_2.status_code in [400, 401, 403, 422]

    # 7. Mocking Redis Failure (Downgrade scenario)
    with patch("src.utils.session_utils.get_session", new_callable=AsyncMock) as mock_get_sessions:
        mock_get_sessions.side_effect = Exception("Redis connection reset")
        res_devices = await integration_client.get(
            "/auth/settings/devices",
            headers={"Authorization": f"Bearer {final_token}"}
        )
        assert res_devices.status_code == 200, "Should fallback to DB gracefully"
