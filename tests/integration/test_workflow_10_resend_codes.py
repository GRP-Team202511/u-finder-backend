# This code was completed by GRP Team 2025.11.
import pytest
from unittest.mock import patch
from sqlalchemy import text
from src.utils.password_utils import hash_token

@pytest.mark.asyncio
async def test_workflow_10_resend_verification(integration_client, real_db):
    sent_codes = []
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    # 1. Sign up normal user
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup = await integration_client.post("/auth/signup", json={
            "email": "resend_user@example.com",
            "name": "Resend User",
            "password": "Password123"
        })
        assert res_signup.status_code == 200
        temp_token = res_signup.json().get("temp_token")
        
        assert len(sent_codes) == 1
        initial_code = sent_codes[-1]

    # Bypass throttle limit
    await real_db.execute(
        text("UPDATE temp_token SET created_at = NOW() - INTERVAL '2 minutes' WHERE token_hashed = :th"),
        {"th": hash_token(temp_token)}
    )
    await real_db.commit()

    # 2. Resend verification code
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_resend = await integration_client.post(
            "/auth/signup/resend",
            headers={"temp-token": temp_token}
        )
        assert res_resend.status_code == 200
        assert res_resend.json()["message"] == "Verification code resent successfully"
        # We reuse the same temp_token
        new_temp_token = temp_token
        
        assert len(sent_codes) == 2
        new_code = sent_codes[-1]
        
        # 3. Old code shouldn't work (if there's a unique temp token hash or just different code)
        res_fail = await integration_client.post(
            "/auth/verify",
            json={"code": initial_code},
            headers={"temp-token": new_temp_token}
        )
        assert res_fail.status_code == 401  # Usually 401 for incorrect code

        # 4. New code works
        res_verify = await integration_client.post(
            "/auth/verify",
            json={"code": new_code},
            headers={"temp-token": new_temp_token}
        )
        assert res_verify.status_code == 201

    # 5. Forgot password
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_reset = await integration_client.post("/auth/reset", json={"email": "resend_user@example.com"})
        assert res_reset.status_code == 200
        reset_temp_token = res_reset.json()["temp_token"]
        assert len(sent_codes) == 3
        first_reset_code = sent_codes[-1]

    # Bypass throttle limit
    await real_db.execute(
        text("UPDATE temp_token SET created_at = NOW() - INTERVAL '2 minutes' WHERE token_hashed = :th"),
        {"th": hash_token(reset_temp_token)}
    )
    await real_db.commit()

    # 6. Resend reset code
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_reset_resend = await integration_client.post(
            "/auth/reset/resend",
            headers={"temp-token": reset_temp_token}
        )
        assert res_reset_resend.status_code == 200
        new_reset_temp_token = reset_temp_token
        assert len(sent_codes) == 4
        new_reset_code = sent_codes[-1]

        # 7. Old reset should fail
        res_reset_fail = await integration_client.post(
            "/auth/reset/verify",
            json={"code": first_reset_code, "new_password": "NewPassword123"},
            headers={"temp-token": new_reset_temp_token}
        )
        assert res_reset_fail.status_code == 401

        # 8. New reset should succeed
        res_reset_verify = await integration_client.post(
            "/auth/reset/verify",
            json={"code": new_reset_code, "new_password": "NewPassword123"},
            headers={"temp-token": new_reset_temp_token}
        )
        assert res_reset_verify.status_code == 200
        assert res_reset_verify.json()["message"] == "Password reset successfully"
