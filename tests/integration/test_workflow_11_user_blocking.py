import pytest
from unittest.mock import patch
from sqlalchemy import text

@pytest.mark.asyncio
async def test_workflow_11_user_blocking(integration_client, real_db):
    sent_codes = []
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    # 1. Sign up normal user
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup_normal = await integration_client.post("/auth/signup", json={
            "email": "blocked_user@example.com",
            "name": "Normal User",
            "password": "Password123"
        })
        assert res_signup_normal.status_code == 200
        temp_token_normal = res_signup_normal.json().get("temp_token")
        
        await integration_client.post("/auth/verify", json={"code": sent_codes[-1]}, headers={"temp-token": temp_token_normal})
        
        normal_login = await integration_client.post("/auth/login", json={
            "email": "blocked_user@example.com",
            "password": "Password123"
        })
        assert normal_login.status_code == 200
        normal_token = normal_login.json()["token"]
        normal_id = normal_login.json()["id"]

    # 2. Normal user tries an endpoint
    res_prof_before = await integration_client.get("/api/profile/personal", headers={"Authorization": f"Bearer {normal_token}"})
    # Might be 404 if profile doesn't exist, but won't be 401/403
    assert res_prof_before.status_code in [200, 404]

    # 3. Create Admin user
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup_admin = await integration_client.post("/auth/signup", json={
            "email": "block_admin@example.com",
            "name": "Admin User",
            "password": "Password123"
        })
        assert res_signup_admin.status_code == 200
        temp_token_admin = res_signup_admin.json().get("temp_token")
        
        await integration_client.post("/auth/verify", json={"code": sent_codes[-1]}, headers={"temp-token": temp_token_admin})

    # Promote admin
    await real_db.execute(text("UPDATE account SET user_type = 3 WHERE email = 'block_admin@example.com'"))
    await real_db.commit()

    admin_login = await integration_client.post("/api/admin/auth/login", json={
        "email": "block_admin@example.com",
        "password": "Password123"
    })
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["token"]

    # 4. Admin blocks normal user
    res_block = await integration_client.post(
        f"/api/admin/users/{normal_id}/block",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert res_block.status_code == 200

    # 5. Normal user tries endpoint -> Session is still valid, so profile might return 404 (doesn't exist)
    res_prof_after = await integration_client.get("/api/profile/personal", headers={"Authorization": f"Bearer {normal_token}"})
    assert res_prof_after.status_code in [200, 404]

    # 6. Normal user tries to login -> should be 403 (blocked)
    normal_login_fail = await integration_client.post("/auth/login", json={
        "email": "blocked_user@example.com",
        "password": "Password123"
    })
    print(normal_login_fail.status_code)
    assert normal_login_fail.status_code == 403

    # 7. Admin unblocks user
    res_unblock = await integration_client.post(
        f"/api/admin/users/{normal_id}/unblock",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert res_unblock.status_code == 200

    # 8. Normal user logs in again
    normal_login_again = await integration_client.post("/auth/login", json={
        "email": "blocked_user@example.com",
        "password": "Password123"
    })
    assert normal_login_again.status_code == 200
    new_normal_token = normal_login_again.json()["token"]

    # 9. Verify token gets access again
    res_prof_final = await integration_client.get("/api/profile/personal", headers={"Authorization": f"Bearer {new_normal_token}"})
    assert res_prof_final.status_code in [200, 404]
