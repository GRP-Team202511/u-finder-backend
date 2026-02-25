"""
Router tests for:
  POST /auth/reset
  POST /auth/reset/verify
  POST /auth/reset/resend
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

from src.utils.password_utils import hash_password


# ── Constants ─────────────────────────────────────────────────────────────────

RESET_URL = "/auth/reset"
RESET_VERIFY_URL = "/auth/reset/verify"
RESET_RESEND_URL = "/auth/reset/resend"

VALID_RESET_VERIFY_PAYLOAD = {
    "code": "123456",
    "newPassword": "NewPass1",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_account(*, user_id: int = 1, email: str = "test@example.com"):
    acc = MagicMock()
    acc.user_id = user_id
    acc.email = email
    acc.password_hashed = hash_password("OldPass1")
    return acc


def _make_reset_token(
    *,
    code: str = "123456",
    expire_at=None,
    created_at=None,
):
    """Return a mock TempToken with token_type='password_reset'."""
    token = MagicMock()
    token.id = 1
    token.user_id = 1
    token.token_hashed = "fake-reset-token"
    token.token_type = "password_reset"
    token.expire_at = expire_at or datetime.now(timezone.utc) + timedelta(hours=1)
    token.created_at = created_at or datetime.now(timezone.utc) - timedelta(seconds=120)
    token.verification_code_hashed = hash_password(code)
    return token


def _two_results(first, second):
    """Side-effect list for two sequential db.execute() calls."""
    r1, r2 = MagicMock(), MagicMock()
    r1.scalar_one_or_none.return_value = first
    r2.scalar_one_or_none.return_value = second
    return [r1, r2]


# ── POST /auth/reset ──────────────────────────────────────────────────────────

class TestResetPassword:
    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock, return_value=True)
    async def test_reset_success(self, mock_email, client, mock_db):
        """Existing email must return 200 with a temp_token."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = _make_account()

        response = await client.post(RESET_URL, json={"email": "test@example.com"})

        assert response.status_code == 200
        body = response.json()
        assert "temp_token" in body
        assert isinstance(body["temp_token"], str)
        assert len(body["temp_token"]) > 0

    async def test_reset_email_not_found(self, client, mock_db):
        """Unknown email must return 404."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.post(RESET_URL, json={"email": "nobody@example.com"})

        assert response.status_code == 404
        assert response.json()["detail"]["message"] == "No account record for this email"

    async def test_reset_invalid_email_format(self, client):
        """Malformed email must return 422."""
        response = await client.post(RESET_URL, json={"email": "not-an-email"})
        assert response.status_code == 422

    async def test_reset_missing_email_field(self, client):
        """Missing email field must return 422."""
        response = await client.post(RESET_URL, json={})
        assert response.status_code == 422


# ── POST /auth/reset/verify ───────────────────────────────────────────────────

class TestResetVerify:
    async def test_reset_verify_success(self, client, mock_db):
        """Correct code + valid token must return 200 with success message."""
        code = "123456"
        reset_token = _make_reset_token(code=code)
        user = _make_account()
        mock_db.execute.side_effect = _two_results(reset_token, user)

        response = await client.post(
            RESET_VERIFY_URL,
            json={"code": code, "newPassword": "NewPass1"},
            headers={"Temp-Token": "fake-reset-token"},
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Password reset successfully"

    async def test_reset_verify_invalid_token(self, client, mock_db):
        """Token not found must return 401."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.post(
            RESET_VERIFY_URL,
            json=VALID_RESET_VERIFY_PAYLOAD,
            headers={"Temp-Token": "bad-token"},
        )

        assert response.status_code == 401
        assert response.json()["detail"]["message"] == "Wrong code or expired token"

    async def test_reset_verify_expired_token(self, client, mock_db):
        """Expired token must return 401."""
        expired = _make_reset_token(expire_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        mock_db.execute.return_value.scalar_one_or_none.return_value = expired

        response = await client.post(
            RESET_VERIFY_URL,
            json=VALID_RESET_VERIFY_PAYLOAD,
            headers={"Temp-Token": "fake-reset-token"},
        )

        assert response.status_code == 401
        assert response.json()["detail"]["message"] == "Wrong code or expired token"

    async def test_reset_verify_wrong_code(self, client, mock_db):
        """Mismatched code must return 401."""
        reset_token = _make_reset_token(code="123456")
        mock_db.execute.return_value.scalar_one_or_none.return_value = reset_token

        response = await client.post(
            RESET_VERIFY_URL,
            json={"code": "999999", "newPassword": "NewPass1"},
            headers={"Temp-Token": "fake-reset-token"},
        )

        assert response.status_code == 401
        assert response.json()["detail"]["message"] == "Wrong code or expired token"

    async def test_reset_verify_weak_new_password(self, client):
        """New password failing strength rules must return 422 (Pydantic)."""
        response = await client.post(
            RESET_VERIFY_URL,
            json={"code": "123456", "newPassword": "weak"},
            headers={"Temp-Token": "fake-reset-token"},
        )
        assert response.status_code == 422

    async def test_reset_verify_missing_temp_token_header(self, client):
        """Missing Temp-Token header must return 422."""
        response = await client.post(RESET_VERIFY_URL, json=VALID_RESET_VERIFY_PAYLOAD)
        assert response.status_code == 422


# ── POST /auth/reset/resend ───────────────────────────────────────────────────

class TestResendResetCode:
    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock, return_value=True)
    async def test_resend_success(self, mock_email, client, mock_db):
        """Valid token outside rate-limit window must return 200."""
        reset_token = _make_reset_token(
            created_at=datetime.now(timezone.utc) - timedelta(seconds=120)
        )
        user = _make_account()
        mock_db.execute.side_effect = _two_results(reset_token, user)

        response = await client.post(RESET_RESEND_URL, headers={"Temp-Token": "fake-reset-token"})

        assert response.status_code == 200
        assert response.json()["message"] == "Verification code resent successfully"

    async def test_resend_invalid_token(self, client, mock_db):
        """Unknown token must return 401."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.post(RESET_RESEND_URL, headers={"Temp-Token": "bad-token"})

        assert response.status_code == 401
        assert response.json()["detail"]["message"] == "Token expired or invalid"

    async def test_resend_expired_token(self, client, mock_db):
        """Expired token must return 401."""
        expired = _make_reset_token(expire_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        mock_db.execute.return_value.scalar_one_or_none.return_value = expired

        response = await client.post(RESET_RESEND_URL, headers={"Temp-Token": "fake-reset-token"})

        assert response.status_code == 401
        assert response.json()["detail"]["message"] == "Token expired or invalid"

    async def test_resend_rate_limited(self, client, mock_db):
        """Request within 60 s of last send must return 429 with retryAfter."""
        reset_token = _make_reset_token(
            created_at=datetime.now(timezone.utc) - timedelta(seconds=10)
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = reset_token

        response = await client.post(RESET_RESEND_URL, headers={"Temp-Token": "fake-reset-token"})

        assert response.status_code == 429
        body = response.json()
        assert "retryAfter" in body["detail"]
        assert body["detail"]["retryAfter"] > 0

    async def test_resend_missing_temp_token_header(self, client):
        """Missing Temp-Token header must return 422."""
        response = await client.post(RESET_RESEND_URL)
        assert response.status_code == 422
