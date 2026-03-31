# This code was completed by GRP Team 2025.11.
"""
Router tests for Turnstile enforcement on auth endpoints.
Verifies that login, signup, and reset properly gate on Turnstile
when it is enabled.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.utils.password_utils import hash_password


# ── Helpers ──

def _turnstile_settings(enabled: bool = True, secret: str = "test-secret"):
    s = MagicMock()
    s.turnstile_enabled = enabled
    s.turnstile_secret_key = secret
    return s


def _make_user(
    *,
    password: str = "Password1",
    email: str = "test@example.com",
    user_id: int = 1,
    user_name: str = "Test User",
    email_verified: bool = True,
    is_blocked: bool = False,
    is_2fa_enabled: bool = False,
):
    user = MagicMock()
    user.user_id = user_id
    user.user_name = user_name
    user.email = email
    user.password_hashed = hash_password(password)
    user.email_verified = email_verified
    user.is_blocked = is_blocked
    user.is_2fa_enabled = is_2fa_enabled
    return user


LOGIN_URL = "/auth/login"
SIGNUP_URL = "/auth/signup"
RESET_URL = "/auth/reset"


# ════════════════════════════════════════════
#  POST /auth/login — Turnstile gate
# ════════════════════════════════════════════
class TestLoginTurnstile:
    """When Turnstile is enabled, login must reject missing/invalid tokens."""

    async def test_login_missing_token_returns_400(self, client):
        """No turnstile_token → 400 before any DB work."""
        with patch("src.routers.auth.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            from fastapi import HTTPException
            mock_verify.side_effect = HTTPException(
                status_code=400, detail={"message": "Missing turnstile_token"}
            )
            response = await client.post(LOGIN_URL, json={
                "email": "test@example.com",
                "password": "Password1",
            })
            assert response.status_code == 400
            assert "Missing" in response.json()["message"]

    async def test_login_invalid_token_returns_400(self, client):
        """Bad turnstile_token → 400."""
        with patch("src.routers.auth.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            from fastapi import HTTPException
            mock_verify.side_effect = HTTPException(
                status_code=400, detail={"message": "Human verification failed"}
            )
            response = await client.post(LOGIN_URL, json={
                "email": "test@example.com",
                "password": "Password1",
                "turnstile_token": "bad-token",
            })
            assert response.status_code == 400
            assert "failed" in response.json()["message"]

    async def test_login_turnstile_503_propagates(self, client):
        """Turnstile API down → 503 to client."""
        with patch("src.routers.auth.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            from fastapi import HTTPException
            mock_verify.side_effect = HTTPException(
                status_code=503, detail={"message": "Human verification service unavailable"}
            )
            response = await client.post(LOGIN_URL, json={
                "email": "test@example.com",
                "password": "Password1",
                "turnstile_token": "some-token",
            })
            assert response.status_code == 503

    @patch("src.routers.auth.save_session", new_callable=AsyncMock)
    async def test_login_valid_token_proceeds(self, mock_save, client, mock_db):
        """Valid Turnstile token → login proceeds normally."""
        user = _make_user()
        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        with patch("src.routers.auth.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = True
            response = await client.post(LOGIN_URL, json={
                "email": "test@example.com",
                "password": "Password1",
                "turnstile_token": "valid-token",
            })
            assert response.status_code == 200
            mock_verify.assert_called_once()


# ════════════════════════════════════════════
#  POST /auth/signup — Turnstile gate
# ════════════════════════════════════════════
class TestSignupTurnstile:
    async def test_signup_missing_token_returns_400(self, client):
        with patch("src.routers.auth.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            from fastapi import HTTPException
            mock_verify.side_effect = HTTPException(
                status_code=400, detail={"message": "Missing turnstile_token"}
            )
            response = await client.post(SIGNUP_URL, json={
                "name": "Test",
                "email": "new@example.com",
                "password": "Password1",
            })
            assert response.status_code == 400
            assert "Missing" in response.json()["message"]

    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock)
    async def test_signup_valid_token_proceeds(self, mock_email, client, mock_db):
        """Valid Turnstile token → signup proceeds (user doesn't exist yet)."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("src.routers.auth.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = True
            response = await client.post(SIGNUP_URL, json={
                "name": "Test",
                "email": "new@example.com",
                "password": "Password1",
                "turnstile_token": "valid-token",
            })
            assert response.status_code == 200
            mock_verify.assert_called_once()


# ════════════════════════════════════════════
#  POST /auth/reset — Turnstile gate
# ════════════════════════════════════════════
class TestResetTurnstile:
    async def test_reset_missing_token_returns_400(self, client):
        with patch("src.routers.auth.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            from fastapi import HTTPException
            mock_verify.side_effect = HTTPException(
                status_code=400, detail={"message": "Missing turnstile_token"}
            )
            response = await client.post(RESET_URL, json={
                "email": "test@example.com",
            })
            assert response.status_code == 400
            assert "Missing" in response.json()["message"]

    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock)
    async def test_reset_valid_token_proceeds(self, mock_email, client, mock_db):
        """Valid Turnstile token → reset proceeds when user exists."""
        user = _make_user()
        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        with patch("src.routers.auth.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = True
            response = await client.post(RESET_URL, json={
                "email": "test@example.com",
                "turnstile_token": "valid-token",
            })
            assert response.status_code == 200
            mock_verify.assert_called_once()

    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock)
    async def test_reset_self_with_valid_auth_skips_turnstile(self, mock_email, client, mock_db):
        """Authenticated user resetting own password → Turnstile is NOT called."""
        user = _make_user(user_id=1, email="test@example.com")
        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        with (
            patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1) as mock_auth,
            patch("src.routers.auth.verify_turnstile_token", new_callable=AsyncMock) as mock_verify,
        ):
            response = await client.post(
                RESET_URL,
                json={"email": "test@example.com"},
                headers={"Authorization": "Bearer valid-token"},
            )
            assert response.status_code == 200
            mock_auth.assert_called_once()
            mock_verify.assert_not_called()

    async def test_reset_with_invalid_auth_still_requires_turnstile(self, client):
        """Invalid Authorization header → Turnstile is still enforced."""
        with (
            patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock) as mock_auth,
            patch("src.routers.auth.verify_turnstile_token", new_callable=AsyncMock) as mock_verify,
        ):
            from fastapi import HTTPException
            mock_auth.side_effect = HTTPException(status_code=401, detail={"message": "Invalid or expired token"})
            mock_verify.side_effect = HTTPException(status_code=400, detail={"message": "Missing turnstile_token"})

            response = await client.post(
                RESET_URL,
                json={"email": "test@example.com"},
                headers={"Authorization": "Bearer bad-token"},
            )
            assert response.status_code == 400
            mock_verify.assert_called_once()

    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock)
    async def test_reset_other_email_with_valid_auth_requires_turnstile(self, mock_email, client, mock_db):
        """Authenticated user resetting ANOTHER user's password → Turnstile IS required."""
        # Auth user is user_id=1, but target email belongs to user_id=2
        target_user = _make_user(user_id=2, email="other@example.com")
        mock_db.execute.return_value.scalar_one_or_none.return_value = target_user

        with (
            patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1) as mock_auth,
            patch("src.routers.auth.verify_turnstile_token", new_callable=AsyncMock, return_value=True) as mock_verify,
        ):
            response = await client.post(
                RESET_URL,
                json={"email": "other@example.com", "turnstile_token": "valid-token"},
                headers={"Authorization": "Bearer valid-token"},
            )
            assert response.status_code == 200
            mock_auth.assert_called_once()
            mock_verify.assert_called_once()
