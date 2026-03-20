import pytest
from httpx import AsyncClient
from unittest.mock import patch
from sqlalchemy import text
import uuid

@pytest.mark.asyncio
async def test_workflow_13_edge_cases(integration_client: AsyncClient, real_db):
    sent_codes = []
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    # 1. Bad Inputs
    res_bad_email = await integration_client.post("/auth/signup", json={
        "email": "not_an_email",
        "name": "Test",
        "password": "Sh" # Short password
    })
    assert res_bad_email.status_code == 422

    # 2. Setup User A and User B
    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        # User A
        res_a = await integration_client.post("/auth/signup", json={"email": "usera@example.com", "name": "User A", "password": "Password123"})
        await integration_client.post("/auth/verify", json={"code": sent_codes[-1]}, headers={"temp-token": res_a.json()["temp_token"]})
        login_a = await integration_client.post("/auth/login", json={"email": "usera@example.com", "password": "Password123"})
        token_a = login_a.json()["token"]
        id_a = login_a.json()["id"]

        # User B
        res_b = await integration_client.post("/auth/signup", json={"email": "userb@example.com", "name": "User B", "password": "Password123"})
        await integration_client.post("/auth/verify", json={"code": sent_codes[-1]}, headers={"temp-token": res_b.json()["temp_token"]})
        login_b = await integration_client.post("/auth/login", json={"email": "userb@example.com", "password": "Password123"})
        token_b = login_b.json()["token"]
        id_b = login_b.json()["id"]

    # 3. Cross-User / Privilege Escalation (IDOR)
    # User A tries to delete User B (admin only endpoint)
    res_bola_admin = await integration_client.delete(f"/api/admin/users/{id_b}", headers={"Authorization": f"Bearer {token_a}"})
    # If standard user, either 401/403
    assert res_bola_admin.status_code in [401, 403, 404]

    # User A tries to access conversation belonging to B
    res_chat_b = await integration_client.post("/chat/conversations", headers={"Authorization": f"Bearer {token_b}"}, json={"title": "B Chat"})
    if res_chat_b.status_code == 200:
        conv_id_b = res_chat_b.json().get("id")
        res_bola_chat = await integration_client.get(f"/chat/conversations/{conv_id_b}/messages", headers={"Authorization": f"Bearer {token_a}"})
        # Should be blocked, either 404 not found or 403
        assert res_bola_chat.status_code in [403, 404]

    # 4. Invalid UUID check
    res_invalid_uuid = await integration_client.post(
        "/profile/liked-university/not-a-uuid",
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert res_invalid_uuid.status_code in [400, 422]
    
    # 5. Non-existent UUID
    res_not_found_uuid = await integration_client.post(
        f"/profile/liked-university/{str(uuid.uuid4())}",
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert res_not_found_uuid.status_code == 404
