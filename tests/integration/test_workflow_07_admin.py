"""
Integration tests for Admin Workflows (Login, User Management, Dashboard).
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch
from sqlalchemy import text

@pytest.mark.asyncio
async def test_workflow_07_admin_operations(integration_client: AsyncClient, real_db):
    sent_codes = []
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    # 1. Create a Normal User
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup_normal = await integration_client.post("/auth/signup", json={
            "email": "normal_user@example.com",
            "name": "Normal User",
            "password": "Password123"
        })
        assert res_signup_normal.status_code == 200
        temp_token_normal = res_signup_normal.json().get("temp_token")
        await integration_client.post("/auth/verify", json={"code": sent_codes[-1]}, headers={"temp-token": temp_token_normal})
        normal_login = await integration_client.post("/auth/login", json={
            "email": "normal_user@example.com",
            "password": "Password123"
        })

        # Get normal_id from db
        res_db = await real_db.execute(text("SELECT user_id FROM account WHERE email = 'normal_user@example.com'"))
        normal_id = res_db.scalar()
        assert normal_id is not None

    # 2. Create an Admin User
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup_admin = await integration_client.post("/auth/signup", json={
            "email": "admin_user@example.com",
            "name": "Admin User",
            "password": "Password123"
        })
        assert res_signup_admin.status_code == 200
        temp_token_admin = res_signup_admin.json().get("temp_token")
        await integration_client.post("/auth/verify", json={"code": sent_codes[-1]}, headers={"temp-token": temp_token_admin})

        # Set user_type = 3 for admin
        await real_db.execute(text("UPDATE account SET user_type = 3 WHERE email = 'admin_user@example.com'"))
        await real_db.commit()
    
    # 3. Admin Login
    res_admin_login = await integration_client.post("/api/admin/auth/login", json={
        "email": "admin_user@example.com",
        "password": "Password123"
    })
    assert res_admin_login.status_code == 200
    admin_token = res_admin_login.json().get("token")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 4. List Users
    res_list = await integration_client.get("/api/admin/users?page_size=10&page_num=1", headers=headers)
    assert res_list.status_code == 200
    users = res_list.json()
    assert isinstance(users, list)
    assert len(users) >= 2
    assert any(u["id"] == normal_id for u in users)

    # 5. Dashboard
    res_dash = await integration_client.get("/api/admin/dashboard/summary", headers=headers)
    assert res_dash.status_code == 200

    # 6. Block User
    res_block = await integration_client.post(f"/api/admin/users/{normal_id}/block", headers=headers)
    assert res_block.status_code == 200

    # 7. Unblock User
    res_unblock = await integration_client.post(f"/api/admin/users/{normal_id}/unblock", headers=headers)
    assert res_unblock.status_code == 200

    # 8. Delete User
    res_delete = await integration_client.delete(f"/api/admin/users/{normal_id}", headers=headers)
    assert res_delete.status_code == 200
