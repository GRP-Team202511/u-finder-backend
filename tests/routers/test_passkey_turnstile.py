# This code was completed by GRP Team 2025.11.
"""
Router tests for Turnstile enforcement on POST /auth/passkey/login/options.
This endpoint is unauthenticated, so Turnstile is critical.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


PASSKEY_LOGIN_OPTIONS_URL = "/auth/passkey/login/options"


def _make_account(
    *,
    user_id: int = 1,
    email: str = "test@example.com",
    email_verified: bool = True,
    passkey_enabled: bool = True,
):
    account = MagicMock()
    account.user_id = user_id
    account.email = email
    account.email_verified = email_verified
    account.passkey_enabled = passkey_enabled
    return account


def _make_passkey(credential_id: str = "Y3JlZGVudGlhbC0x"):
    pk = MagicMock()
    pk.credential_id = credential_id
    pk.is_active = True
    return pk


class TestPasskeyLoginOptionsTurnstile:
    """Turnstile gate on the unauthenticated passkey login/options endpoint."""

    async def test_missing_token_returns_400(self, client):
        """No turnstile_token → 400 before any DB lookup."""
        with patch("src.routers.passkey.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            from fastapi import HTTPException
            mock_verify.side_effect = HTTPException(
                status_code=400, detail={"message": "Missing turnstile_token"}
            )
            response = await client.post(PASSKEY_LOGIN_OPTIONS_URL, json={
                "email": "test@example.com",
            })
            assert response.status_code == 400
            assert "Missing" in response.json()["message"]

    async def test_invalid_token_returns_400(self, client):
        """Bad turnstile_token → 400."""
        with patch("src.routers.passkey.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            from fastapi import HTTPException
            mock_verify.side_effect = HTTPException(
                status_code=400, detail={"message": "Human verification failed"}
            )
            response = await client.post(PASSKEY_LOGIN_OPTIONS_URL, json={
                "email": "test@example.com",
                "turnstile_token": "bad-token",
            })
            assert response.status_code == 400
            assert "failed" in response.json()["message"]

    async def test_turnstile_503_propagates(self, client):
        """Turnstile API down → 503."""
        with patch("src.routers.passkey.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            from fastapi import HTTPException
            mock_verify.side_effect = HTTPException(
                status_code=503, detail={"message": "Human verification service unavailable"}
            )
            response = await client.post(PASSKEY_LOGIN_OPTIONS_URL, json={
                "email": "test@example.com",
                "turnstile_token": "some-token",
            })
            assert response.status_code == 503

    async def test_valid_token_proceeds_to_user_lookup(self, client, mock_db):
        """Valid Turnstile token → endpoint proceeds (user not found is fine here)."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("src.routers.passkey.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = True
            response = await client.post(PASSKEY_LOGIN_OPTIONS_URL, json={
                "email": "test@example.com",
                "turnstile_token": "valid-token",
            })
            # 404 means Turnstile passed and the endpoint hit DB (user not found)
            assert response.status_code == 404
            mock_verify.assert_called_once()
