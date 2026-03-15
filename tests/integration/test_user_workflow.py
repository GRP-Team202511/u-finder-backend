"""
Integration tests for complete user workflows.
Simulates a user's journey through multiple API endpoints:
Signup -> Verify -> Login -> Profile -> Logout
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from tests.routers.utils.response_asserts import (
    assert_signup_200,
    assert_verify_signup_200,
    assert_login_200,
    assert_personal_info_200,
    assert_message_response,
)

def _make_account(*, user_id=1, email="test@example.com", user_name="Test User", email_verified=False, disabled=False):
    acc = MagicMock()
    acc.user_id = user_id
    acc.email = email
    acc.user_name = user_name
    acc.email_verified = email_verified
    acc.is_blocked = disabled
    acc.password_hash = "fake_hash"
    acc.created_at = "2024-01-01T00:00:00"
    acc.is_2fa_enabled = False
    
    # Nested profile
    prof = MagicMock()
    prof.user_id = user_id
    prof.basic_info = {"name": user_name, "gender": "unknown", "birthday": "2000-01-01"}
    prof.account = acc
    acc.profile = prof
    
    return acc

def _make_temp_token(token_hashed="fake_hash", code="123456"):
    from datetime import datetime, timedelta, timezone
    from src.utils.password_utils import hash_password
    
    token = MagicMock()
    token.id = 1
    token.user_id = 99
    token.token_hashed = token_hashed
    token.token_type = "email_verify"
    token.expire_at = datetime.now(timezone.utc) + timedelta(hours=24)
    token.created_at = datetime.now(timezone.utc)
    token.verification_code_hashed = hash_password(code)
    return token

def _sequence_results(*results):
    """Return a side_effect list for sequential db.execute() calls."""
    mocks = []
    for r in results:
        m = MagicMock()
        m.scalar_one_or_none.return_value = r
        mocks.append(m)
    return mocks

@pytest.mark.asyncio
async def test_user_signup_to_logout_workflow(client, mock_db, mock_redis):
    """
    Simulates a full user journey:
    1. POST /auth/signup (User registration)
    2. POST /auth/verify (User verifies email)
    3. POST /auth/login (User logs in)
    4. GET /profile/personal (User fetches profile)
    5. POST /auth/logout (User logs out)
    """

    user_email = "integration@example.com"
    user_password = "Password123"
    fake_user_id = 99

    # ────────────────────────────────────────────────────────
    # 1. Signup
    # ────────────────────────────────────────────────────────
    # Mocking for signup: First DB check for existing user (returns None)
    # the router sends verification email inside signup route
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    with patch("src.routers.auth.send_verification_email") as mock_send_email:
        signup_payload = {
            "email": user_email,
            "password": user_password,
            "name": "Integration User"
        }
        res_signup = await client.post("/auth/signup", json=signup_payload)
        
        assert res_signup.status_code == 200
        assert_signup_200(res_signup.json())
        
        # Extract temp_token
        temp_token = res_signup.json()["temp_token"]

        # Ensure email was triggered
        mock_send_email.assert_called_once()
        
    # ────────────────────────────────────────────────────────
    # 2. Verify Email
    # ────────────────────────────────────────────────────────
        # Mocking for verify: DB needs to find temp_token, then find user
        
        pending_account = _make_account(user_id=fake_user_id, email=user_email, email_verified=False)
        temp_token_record = _make_temp_token(code="123456")
        
        mock_db.execute.side_effect = _sequence_results(temp_token_record, pending_account)

        verify_payload = {
            "code": "123456"
        }
        
        res_verify = await client.post(
            "/auth/verify", 
            json=verify_payload,
            headers={"Temp-Token": temp_token}
        )
        assert res_verify.status_code == 201, f"Verify failed: {res_verify.text}"
        assert_verify_signup_200(res_verify.json())
        
        # ────────────────────────────────────────────────────────
        # 3. Login
        # ────────────────────────────────────────────────────────
        # Once verified, account.email_verified became True
        verified_account = _make_account(user_id=fake_user_id, email=user_email, email_verified=True)
        
        with patch("src.routers.auth.verify_password", return_value=True), patch("src.routers.auth.save_session", new_callable=AsyncMock):
            # We need mock_db.execute to return verified_account
            mock_db.execute.side_effect = _sequence_results(verified_account)
            
            login_payload = {
                "email": user_email,
                "password": user_password
            }
            
            res_login = await client.post("/auth/login", json=login_payload)
            assert res_login.status_code == 200, f"Login failed: {res_login.text}"
            assert_login_200(res_login.json())
            
            # Extract session token from response
            resp_json = res_login.json()
            session_token = resp_json["token"]
            
        # ────────────────────────────────────────────────────────
        # 4. Access Profile
        # ────────────────────────────────────────────────────────
        # For profile, we must be authenticated. The dependency get_session uses redis
        # To mock redis hit:
        mock_redis.hgetall.return_value = {
            "user_id": str(fake_user_id),
            "user_agent": "pytest"
        }

        # DB will fetch the account, then the profile
        mock_db.execute.side_effect = _sequence_results(verified_account, verified_account.profile)

        res_profile = await client.get(
            "/profile/personal",
            headers={"Authorization": f"Bearer {session_token}"}
        )
        assert res_profile.status_code == 200, f"Profile GET failed: {res_profile.text}"
        assert_personal_info_200(res_profile.json())

        # ────────────────────────────────────────────────────────
        # 5. Logout
        # ────────────────────────────────────────────────────────
        # User is authenticated via session token.
        logout_payload = {"session_token": session_token}
        
        # Logout searches for the token in DB and clears redis session
        mock_token_record = MagicMock()
        mock_token_record.token = session_token
        mock_db.execute.side_effect = _sequence_results(mock_token_record)

        # Mock delete session to avoid Redis pipeline crash
        with patch("src.routers.auth.delete_session", new_callable=AsyncMock):
            res_logout = await client.post(
                "/auth/logout",
                headers={"Authorization": f"Bearer {session_token}"},
                json=logout_payload
            )
            assert res_logout.status_code == 200, f"Logout failed: {res_logout.text}"
            assert_message_response(res_logout.json(), "Logged out successfully")
