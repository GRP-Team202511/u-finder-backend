import pytest
from unittest.mock import patch

@pytest.mark.asyncio
async def test_workflow_09_account_maintenance(integration_client, real_db):
    sent_codes = []
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    # 1. Sign up normal user
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup = await integration_client.post("/auth/signup", json={
            "email": "maintenance_user@example.com",
            "name": "Old Name",
            "password": "Password123"
        })
        assert res_signup.status_code == 200
        temp_token = res_signup.json().get("temp_token")
        
        # Verify account
        await integration_client.post("/auth/verify", json={"code": sent_codes[-1]}, headers={"temp-token": temp_token})

    # 2. Login
    res_login = await integration_client.post("/auth/login", json={
        "email": "maintenance_user@example.com",
        "password": "Password123"
    })
    assert res_login.status_code == 200
    token = res_login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Update Username
    res_update_username = await integration_client.put("/auth/settings/username", json={"username": "New Name"}, headers=headers)
    assert res_update_username.status_code == 200
    assert res_update_username.json()["message"] == "Username updated successfully"

    # 4. Initiate Account Deletion
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_delete_init = await integration_client.delete("/auth/delete", headers=headers)
        assert res_delete_init.status_code == 200
        delete_data = res_delete_init.json()
        assert delete_data["verification"] == "email"
        delete_temp_token = delete_data["temp_token"]

    # 5. Verify Deletion
    res_delete_verify = await integration_client.post("/auth/delete/email", json={"code": sent_codes[-1]}, headers={"temp-token": delete_temp_token})
    assert res_delete_verify.status_code == 200
    assert res_delete_verify.json()["message"] == "Account deleted successfully"

    # 6. Try to login again (Should fail)
    res_login_after_delete = await integration_client.post("/auth/login", json={
        "email": "maintenance_user@example.com",
        "password": "Password123"
    })
    assert res_login_after_delete.status_code == 404
