"""
Router tests for POST /auth/login
"""
import pytest
from unittest.mock import patch, AsyncMock
from src.utils.password_utils import hash_password
from tests.routers.utils.response_asserts import (
    assert_login_200,
    assert_message_response,
    assert_validation_error,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(
    *,
    password: str = "Password1",
    is_blocked: bool = False,
    email_verified: bool = True,
    is_2fa_enabled: bool = False,
    user_id: int = 1,
    user_name: str = "Test User",
    email: str = "test@example.com",
):
    """Return a minimal mock Account object for login tests."""
    from unittest.mock import MagicMock

    user = MagicMock()
    user.user_id = user_id
    user.user_name = user_name
    user.email = email
    user.password_hashed = hash_password(password)
    user.is_blocked = is_blocked
    user.email_verified = email_verified
    user.is_2fa_enabled = is_2fa_enabled
    return user


LOGIN_URL = "/auth/login"
VALID_PAYLOAD = {"email": "test@example.com", "password": "Password1"}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestLogin:
    @patch("src.routers.auth.save_session", new_callable=AsyncMock)
    async def test_login_success(self, mock_save_session, client, mock_db):
        """Valid credentials must return 200 with id, name, and token."""
        user = _make_user()
        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        response = await client.post(LOGIN_URL, json=VALID_PAYLOAD)

        assert response.status_code == 200
        body = response.json()
        assert_login_200(body)
        assert body["id"] == user.user_id
        assert body["name"] == user.user_name

    async def test_login_user_not_found(self, client, mock_db):
        """Unknown email must return 404."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.post(LOGIN_URL, json=VALID_PAYLOAD)

        assert response.status_code == 404
        assert_message_response(response.json(), "User not found")

    @patch("src.routers.auth.save_session", new_callable=AsyncMock)
    async def test_login_wrong_password(self, mock_save_session, client, mock_db):
        """Incorrect password must return 401."""
        user = _make_user(password="CorrectPass1")
        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        response = await client.post(
            LOGIN_URL, json={"email": "test@example.com", "password": "WrongPass1"}
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Incorrect password")

    @patch("src.routers.auth.save_session", new_callable=AsyncMock)
    async def test_login_blocked_account(self, mock_save_session, client, mock_db):
        """A blocked account must return 403."""
        user = _make_user(is_blocked=True)
        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        response = await client.post(LOGIN_URL, json=VALID_PAYLOAD)

        assert response.status_code == 403
        assert_message_response(response.json(), "Account is blocked")

    async def test_login_unverified_email(self, client, mock_db):
        """An unverified account is treated as non-existent."""
        user = _make_user(email_verified=False)
        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        response = await client.post(LOGIN_URL, json=VALID_PAYLOAD)

        assert response.status_code == 404
        assert_message_response(response.json(), "User not found")

    async def test_login_invalid_email_format(self, client):
        """A malformed email must return 422 (Pydantic validation)."""
        response = await client.post(
            LOGIN_URL, json={"email": "not-an-email", "password": "Password1"}
        )
        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_login_missing_password(self, client):
        """Missing password field must return 422."""
        response = await client.post(LOGIN_URL, json={"email": "test@example.com"})
        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_login_missing_email(self, client):
        """Missing email field must return 422."""
        response = await client.post(LOGIN_URL, json={"password": "Password1"})
        assert response.status_code == 422
        assert_validation_error(response.json())

    @patch("src.routers.auth.save_session", new_callable=AsyncMock)
    async def test_login_email_case_insensitive(self, mock_save_session, client, mock_db):
        """Email lookup must be case-insensitive (normalised to lowercase)."""
        user = _make_user(email="test@example.com")
        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        response = await client.post(
            LOGIN_URL, json={"email": "TEST@EXAMPLE.COM", "password": "Password1"}
        )

        assert response.status_code == 200
        body = response.json()
        assert_login_200(body)
        assert body["id"] == user.user_id
        assert body["name"] == user.user_name
