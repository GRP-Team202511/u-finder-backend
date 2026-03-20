"""
Integration tests for User Devices / Multi-Login Flow.
"""
import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from unittest.mock import patch

@pytest.mark.asyncio
async def test_workflow_04_devices(integration_client: AsyncClient, real_redis: Redis):
    # 1. Signup a user 
    sent_codes = []
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup = await integration_client.post("/auth/signup", json={
            "email": "devices_test@example.com",
            "name": "Devices Test",
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

    # 2. Login from Device A
    res_login_a = await integration_client.post(
        "/auth/login", 
        json={"email": "devices_test@example.com", "password": "Password123"},
        headers={"User-Agent": "Device-A/1.0"}
    )
    assert res_login_a.status_code == 200
    token_a = res_login_a.json().get("token")

    # Get Device A session ID
    res_devices_a = await integration_client.get(
        "/auth/settings/devices",
        headers={"Authorization": f"Bearer {token_a}"}
    )
    session_id_a = None
    for d in res_devices_a.json().get("devices", []):
        if d.get("is_current"):
            session_id_a = d.get("session_id")
            break
    
    assert session_id_a is not None

    # 3. Login from Device B
    res_login_b = await integration_client.post(
        "/auth/login", 
        json={"email": "devices_test@example.com", "password": "Password123"},
        headers={"User-Agent": "Device-B/2.0"}
    )
    assert res_login_b.status_code == 200
    token_b = res_login_b.json().get("token")

    # 4. List Devices using token_b
    res_devices = await integration_client.get(
        "/auth/settings/devices",
        headers={"Authorization": f"Bearer {token_b}"}
    )
    assert res_devices.status_code == 200
    devices_data = res_devices.json().get("devices", [])
    assert len(devices_data) == 3

    # 5. Logout Device A from Device B
    res_kick = await integration_client.delete(
        f"/auth/settings/devices/{session_id_a}",
        headers={"Authorization": f"Bearer {token_b}"}
    )
    assert res_kick.status_code == 200

    # 6. Verify Device A is kicked out (Token invalid)
    res_info_a = await integration_client.get(
        "/auth/settings/info",
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert res_info_a.status_code == 401

    # 7. Device B continues to work
    res_info_b = await integration_client.get(
        "/auth/settings/info",
        headers={"Authorization": f"Bearer {token_b}"}
    )
    assert res_info_b.status_code == 200

    # 8. Logout All (from Device B)
    res_logout_all = await integration_client.post(
        "/auth/settings/logout-all",
        headers={"Authorization": f"Bearer {token_b}"}
    )
    assert res_logout_all.status_code == 200

    # 9. Verify Device B is now kicked out
    res_info_b_after = await integration_client.get(
        "/auth/settings/info",
        headers={"Authorization": f"Bearer {token_b}"}
    )
    assert res_info_b_after.status_code == 401