# This code was completed by GRP Team 2025.11.
import pytest
from unittest.mock import patch
from sqlalchemy import text
from src.utils.cleanup import cleanup_expired_refresh_tokens

@pytest.mark.asyncio
async def test_workflow_12_token_expiration(integration_client, real_db, real_redis):
    sent_codes = []
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    # 1. Sign up normal user
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup = await integration_client.post("/auth/signup", json={
            "email": "expire_user@example.com",
            "name": "Expire User",
            "password": "Password123"
        })
        assert res_signup.status_code == 200
        temp_token = res_signup.json().get("temp_token")
        
        await integration_client.post("/auth/verify", json={"code": sent_codes[-1]}, headers={"temp-token": temp_token})
        
    # 2. Login successfully
    res_login = await integration_client.post("/auth/login", json={
        "email": "expire_user@example.com",
        "password": "Password123"
    })
    assert res_login.status_code == 200
    token = res_login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Access endpoint successfully
    res_prof_before = await integration_client.get("/profile/personal", headers=headers)
    assert res_prof_before.status_code in [200, 404]  # 404 if profile empty, not 401
    
    # 4. Manually expire the refresh token in the database
    # Assuming token is stored in refresh_token table and we can expire it
    result = await real_db.execute(
        text("SELECT user_id FROM account WHERE email = :email"),
        {"email": "expire_user@example.com"},
    )
    user_id = result.scalar()
    await real_db.execute(
        text("UPDATE refresh_token SET expire_at = NOW() - INTERVAL '1 day' WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
    await real_db.commit()
    
    # Call cleanup job to wipe expired tokens
    await cleanup_expired_refresh_tokens(real_db, real_redis)

    # Flush redis since get_current_user_id uses Redis cache first
    await real_redis.flushdb()
    res_prof_after = await integration_client.get("/profile/personal", headers=headers)
    assert res_prof_after.status_code == 401

    # 6. User logs in again
    res_login_again = await integration_client.post("/auth/login", json={
        "email": "expire_user@example.com",
        "password": "Password123"
    })
    assert res_login_again.status_code == 200
    new_token = res_login_again.json()["token"]

    # 7. Endpoint works again
    res_prof_final = await integration_client.get("/profile/personal", headers={"Authorization": f"Bearer {new_token}"})
    assert res_prof_final.status_code in [200, 404]

    # 8. User logs out
    res_logout = await integration_client.post("/auth/logout", headers={"Authorization": f"Bearer {new_token}"})
    assert res_logout.status_code == 200

    # 9. Endpoint fails after logout
    res_prof_post_logout = await integration_client.get("/profile/personal", headers={"Authorization": f"Bearer {new_token}"})
    assert res_prof_post_logout.status_code == 401
