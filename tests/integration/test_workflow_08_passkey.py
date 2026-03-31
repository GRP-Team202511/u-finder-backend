# This code was completed by GRP Team 2025.11.
import pytest
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_workflow_08_passkey_operations(integration_client, real_db):
    sent_codes = []
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    # 1. Sign up user
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        user_payload = {
            "email": "passkey_user@example.com",
            "name": "PasskeyUser",
            "password": "Password123!"
        }
        res_signup = await integration_client.post("/auth/signup", json=user_payload)
        assert res_signup.status_code == 200
        temp_token = res_signup.json().get("temp_token")
        
        res_verify = await integration_client.post("/auth/verify", json={"code": sent_codes[-1]}, headers={"temp-token": temp_token})
        assert res_verify.status_code == 201

    res_login = await integration_client.post("/auth/login", json={
        "email": "passkey_user@example.com",
        "password": "Password123!"
    })
    assert res_login.status_code == 200
    token = res_login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Get register options
    res_reg_opts = await integration_client.post("/auth/passkey/register/options", headers=headers)
    assert res_reg_opts.status_code == 200
    opts_data = res_reg_opts.json()
    assert "options" in opts_data

    # 3. Verify register
    mock_reg_verification = MagicMock()
    mock_reg_verification.credential_id = b"credential_id_123"
    mock_reg_verification.credential_public_key = b"public_key_abc"
    mock_reg_verification.sign_count = 0

    with patch("src.routers.passkey.verify_registration_response", return_value=mock_reg_verification):
        reg_verify_payload = {
            "credential": {"id": "dummy_credential_id", "rawId": "dummy_raw_id", "type": "public-key"}
        }
        res_reg_verify = await integration_client.post("/auth/passkey/register/verify", headers=headers, json=reg_verify_payload)
        assert res_reg_verify.status_code == 200
        assert res_reg_verify.json()["message"] == "Passkey registered successfully"

    # 4. Get login options
    res_log_opts = await integration_client.post("/auth/passkey/login/options", json={"email": "passkey_user@example.com"})
    assert res_log_opts.status_code == 200
    log_opts_data = res_log_opts.json()
    assert "options" in log_opts_data

    # 5. Verify login
    mock_log_verification = MagicMock()
    mock_log_verification.credential_id = b"credential_id_123"
    mock_log_verification.new_sign_count = 1

    with patch("src.routers.passkey.verify_authentication_response", return_value=mock_log_verification):
        log_verify_payload = {
            "email": "passkey_user@example.com",
            "credential": {"id": "Y3JlZGVudGlhbF9pZF8xMjM", "rawId": "dummy_raw_id", "type": "public-key"}
        }
        res_log_verify = await integration_client.post("/auth/passkey/login/verify", json=log_verify_payload)
        assert res_log_verify.status_code == 200
        log_verify_data = res_log_verify.json()
        assert "token" in log_verify_data
        assert log_verify_data["id"] > 0
