# This code was completed by GRP Team 2025.11.
"""
Router tests for account deletion endpoints:
  - DELETE /auth/delete
  - POST   /auth/delete/2fa
  - POST   /auth/delete/email

Authentication strategy (same as other auth tests):
  - Auth success: mock_redis.hgetall returns {"user_id": "1", "user_agent": "pytest"}
  - Auth fail (401): hgetall returns {} + DB returns None
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.utils.password_utils import hash_password
from tests.routers.utils.response_asserts import assert_message_response

BEARER = "Bearer fake-delete-test-token"
AUTH_HEADERS = {"Authorization": BEARER}

DELETE_URL = "/auth/delete"
DELETE_2FA_URL = "/auth/delete/2fa"
DELETE_EMAIL_URL = "/auth/delete/email"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _setup_redis_hit(mock_redis):
    """Configure Redis to return a valid session (auth via cache)."""
    mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}


def _make_account(*, is_2fa_enabled=False, totp_secret_encrypted=None):
    """Return a mock Account for delete tests."""
    acc = MagicMock()
    acc.user_id = 1
    acc.user_name = "Test User"
    acc.email = "test@example.com"
    acc.password_hashed = hash_password("Password1")
    acc.is_blocked = False
    acc.email_verified = True
    acc.is_2fa_enabled = is_2fa_enabled
    acc.totp_secret_encrypted = totp_secret_encrypted
    return acc


def _make_temp_token(*, user_id=1, expired=False, verification_code_hashed=None):
    """Return a mock TempToken for delete verification."""
    token = MagicMock()
    token.user_id = user_id
    token.token_type = "delete_account"
    if expired:
        token.expire_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    else:
        token.expire_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    token.verification_code_hashed = verification_code_hashed
    return token


def _db_result(value):
    """Return an execute result whose scalar_one_or_none() yields *value*."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _db_scalars_all(values):
    """Return an execute result whose scalars().all() yields *values*."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


# ═══════════════════════════════════════════════════════════════════════════════
#  DELETE /auth/delete
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeleteAccount:

    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock, return_value=True)
    async def test_delete_initiate_email_path(self, mock_send_email, client, mock_db, mock_redis):
        """Non-2FA user → 200 with verification='email', email sent."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=False)
        mock_db.execute.return_value = _db_result(account)

        response = await client.delete(DELETE_URL, headers=AUTH_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["verification"] == "email"
        assert isinstance(body["temp_token"], str) and body["temp_token"]
        mock_send_email.assert_called_once()
        # Verify email_type is "delete"
        call_kwargs = mock_send_email.call_args
        assert call_kwargs.kwargs.get("email_type") == "delete" or call_kwargs[1].get("email_type") == "delete"

    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock, return_value=False)
    async def test_delete_initiate_email_send_failure(self, mock_send_email, client, mock_db, mock_redis):
        """Email send fails → 500, temp token cleaned up."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=False)
        mock_db.execute.return_value = _db_result(account)

        response = await client.delete(DELETE_URL, headers=AUTH_HEADERS)

        assert response.status_code == 500
        assert_message_response(response.json(), "Failed to send verification email. Please try again later.")
        # Verify temp token was cleaned up (db.delete called)
        mock_db.delete.assert_awaited()

    async def test_delete_initiate_2fa_path(self, client, mock_db, mock_redis):
        """2FA user → 200 with verification='2fa', no email sent."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc_secret")
        mock_db.execute.return_value = _db_result(account)

        response = await client.delete(DELETE_URL, headers=AUTH_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["verification"] == "2fa"
        assert isinstance(body["temp_token"], str) and body["temp_token"]

    async def test_delete_unauthorized_no_token(self, client, mock_db, mock_redis):
        """Missing Authorization header → 422."""
        response = await client.delete(DELETE_URL)
        assert response.status_code == 422

    async def test_delete_unauthorized_invalid_token(self, client, mock_db, mock_redis):
        """Invalid Bearer token → 401."""
        response = await client.delete(DELETE_URL, headers={"Authorization": "Bearer bad-token"})
        assert response.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
#  POST /auth/delete/2fa
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerifyDelete2FA:

    @patch("src.routers.auth.delete_all_user_sessions", new_callable=AsyncMock, return_value=1)
    @patch("src.routers.auth.check_totp_replay", return_value=False)
    @patch("src.routers.auth.decrypt_secret", return_value="JBSWY3DPEHPK3PXP")
    @patch("src.routers.auth.verify_totp_code", return_value=True)
    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_2fa_totp_success(
        self, mock_hash, mock_verify, mock_decrypt, mock_replay, mock_del_sessions,
        client, mock_db, mock_redis
    ):
        """Valid TOTP code → 200, account deleted."""
        token_record = _make_temp_token()
        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc_secret")

        mock_db.execute.side_effect = [
            _db_result(token_record),  # TempToken lookup
            _db_result(account),       # Account lookup
        ]

        response = await client.post(
            DELETE_2FA_URL,
            headers={"Temp-Token": "valid-temp-token"},
            json={"code": "123456"},
        )

        assert response.status_code == 200
        assert_message_response(response.json(), "Account deleted successfully")
        mock_del_sessions.assert_called_once_with(mock_redis, account.user_id)
        # Verify db.delete was called for both token_record and user
        assert mock_db.delete.await_count == 2

    @patch("src.routers.auth.delete_all_user_sessions", new_callable=AsyncMock, return_value=1)
    @patch("src.routers.auth.verify_password", return_value=True)
    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_2fa_backup_code_success(
        self, mock_hash, mock_verify_pw, mock_del_sessions,
        client, mock_db, mock_redis
    ):
        """Valid backup code → 200, account deleted."""
        token_record = _make_temp_token()
        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc_secret")

        backup_code = MagicMock()
        backup_code.user_id = 1
        backup_code.code_hashed = "$2b$12$placeholder"
        backup_code.is_used = False

        mock_db.execute.side_effect = [
            _db_result(token_record),       # TempToken lookup
            _db_result(account),            # Account lookup
            _db_scalars_all([backup_code]), # backup codes lookup
        ]

        response = await client.post(
            DELETE_2FA_URL,
            headers={"Temp-Token": "valid-temp-token"},
            json={"code": "A1B2C3D4"},
        )

        assert response.status_code == 200
        assert_message_response(response.json(), "Account deleted successfully")

    @patch("src.routers.auth.decrypt_secret", return_value="JBSWY3DPEHPK3PXP")
    @patch("src.routers.auth.verify_totp_code", return_value=False)
    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_2fa_invalid_code(
        self, mock_hash, mock_verify, mock_decrypt, client, mock_db, mock_redis
    ):
        """Wrong TOTP code → 400."""
        token_record = _make_temp_token()
        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc_secret")

        mock_db.execute.side_effect = [
            _db_result(token_record),
            _db_result(account),
        ]

        response = await client.post(
            DELETE_2FA_URL,
            headers={"Temp-Token": "valid-temp-token"},
            json={"code": "000000"},
        )

        assert response.status_code == 400
        assert_message_response(response.json(), "Invalid verification code")

    @patch("src.routers.auth.check_totp_replay", return_value=True)
    @patch("src.routers.auth.decrypt_secret", return_value="JBSWY3DPEHPK3PXP")
    @patch("src.routers.auth.verify_totp_code", return_value=True)
    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_2fa_totp_replay_rejected(
        self, mock_hash, mock_verify, mock_decrypt, mock_replay,
        client, mock_db, mock_redis
    ):
        """Replayed TOTP code → 400."""
        token_record = _make_temp_token()
        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc_secret")

        mock_db.execute.side_effect = [
            _db_result(token_record),
            _db_result(account),
        ]

        response = await client.post(
            DELETE_2FA_URL,
            headers={"Temp-Token": "valid-temp-token"},
            json={"code": "123456"},
        )

        assert response.status_code == 400
        assert_message_response(response.json(), "TOTP code already used, please wait for a new code")

    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_2fa_invalid_temp_token(self, mock_hash, client, mock_db, mock_redis):
        """Non-existent temp token → 401."""
        mock_db.execute.return_value = _db_result(None)

        response = await client.post(
            DELETE_2FA_URL,
            headers={"Temp-Token": "bad-token"},
            json={"code": "123456"},
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_2fa_expired_temp_token(self, mock_hash, client, mock_db, mock_redis):
        """Expired temp token → 401."""
        token_record = _make_temp_token(expired=True)
        mock_db.execute.return_value = _db_result(token_record)

        response = await client.post(
            DELETE_2FA_URL,
            headers={"Temp-Token": "expired-token"},
            json={"code": "123456"},
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_2fa_user_not_found(self, mock_hash, client, mock_db, mock_redis):
        """Temp token exists but user not found → 401."""
        token_record = _make_temp_token()

        mock_db.execute.side_effect = [
            _db_result(token_record),  # TempToken lookup
            _db_result(None),          # Account lookup → None
        ]

        response = await client.post(
            DELETE_2FA_URL,
            headers={"Temp-Token": "valid-temp-token"},
            json={"code": "123456"},
        )

        assert response.status_code == 401

    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_2fa_user_without_2fa_enabled(self, mock_hash, client, mock_db, mock_redis):
        """User exists but 2FA not enabled → 401."""
        token_record = _make_temp_token()
        account = _make_account(is_2fa_enabled=False)

        mock_db.execute.side_effect = [
            _db_result(token_record),
            _db_result(account),
        ]

        response = await client.post(
            DELETE_2FA_URL,
            headers={"Temp-Token": "valid-temp-token"},
            json={"code": "123456"},
        )

        assert response.status_code == 401

    async def test_2fa_missing_temp_token_header(self, client, mock_db, mock_redis):
        """Missing Temp-Token header → 422."""
        response = await client.post(
            DELETE_2FA_URL,
            json={"code": "123456"},
        )
        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
#  POST /auth/delete/email
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerifyDeleteEmail:

    @patch("src.routers.auth.delete_all_user_sessions", new_callable=AsyncMock, return_value=1)
    @patch("src.routers.auth.verify_password", return_value=True)
    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_email_verify_success(
        self, mock_hash, mock_verify_pw, mock_del_sessions,
        client, mock_db, mock_redis
    ):
        """Valid email code → 200, account deleted."""
        token_record = _make_temp_token(verification_code_hashed="$2b$12$hashed_code")
        account = _make_account(is_2fa_enabled=False)

        mock_db.execute.side_effect = [
            _db_result(token_record),  # TempToken lookup
            _db_result(account),       # Account lookup
        ]

        response = await client.post(
            DELETE_EMAIL_URL,
            headers={"Temp-Token": "valid-temp-token"},
            json={"code": "482916"},
        )

        assert response.status_code == 200
        assert_message_response(response.json(), "Account deleted successfully")
        mock_del_sessions.assert_called_once_with(mock_redis, account.user_id)
        assert mock_db.delete.await_count == 2

    @patch("src.routers.auth.verify_password", return_value=False)
    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_email_wrong_code(
        self, mock_hash, mock_verify_pw, client, mock_db, mock_redis
    ):
        """Wrong email verification code → 401."""
        token_record = _make_temp_token(verification_code_hashed="$2b$12$hashed_code")

        mock_db.execute.return_value = _db_result(token_record)

        response = await client.post(
            DELETE_EMAIL_URL,
            headers={"Temp-Token": "valid-temp-token"},
            json={"code": "000000"},
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Wrong code or expired token")

    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_email_no_code_stored(self, mock_hash, client, mock_db, mock_redis):
        """Token has no verification_code_hashed → 401."""
        token_record = _make_temp_token(verification_code_hashed=None)

        mock_db.execute.return_value = _db_result(token_record)

        response = await client.post(
            DELETE_EMAIL_URL,
            headers={"Temp-Token": "valid-temp-token"},
            json={"code": "123456"},
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Wrong code or expired token")

    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_email_invalid_temp_token(self, mock_hash, client, mock_db, mock_redis):
        """Non-existent temp token → 401."""
        mock_db.execute.return_value = _db_result(None)

        response = await client.post(
            DELETE_EMAIL_URL,
            headers={"Temp-Token": "bad-token"},
            json={"code": "123456"},
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_email_expired_temp_token(self, mock_hash, client, mock_db, mock_redis):
        """Expired temp token → 401."""
        token_record = _make_temp_token(expired=True)
        mock_db.execute.return_value = _db_result(token_record)

        response = await client.post(
            DELETE_EMAIL_URL,
            headers={"Temp-Token": "expired-token"},
            json={"code": "123456"},
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    @patch("src.routers.auth.verify_password", return_value=True)
    @patch("src.routers.auth.hash_token", return_value="hashed_temp")
    async def test_email_user_not_found(
        self, mock_hash, mock_verify_pw, client, mock_db, mock_redis
    ):
        """Code is correct but user not found → 401."""
        token_record = _make_temp_token(verification_code_hashed="$2b$12$hashed_code")

        mock_db.execute.side_effect = [
            _db_result(token_record),  # TempToken lookup
            _db_result(None),          # Account lookup → None
        ]

        response = await client.post(
            DELETE_EMAIL_URL,
            headers={"Temp-Token": "valid-temp-token"},
            json={"code": "482916"},
        )

        assert response.status_code == 401

    async def test_email_missing_temp_token_header(self, client, mock_db, mock_redis):
        """Missing Temp-Token header → 422."""
        response = await client.post(
            DELETE_EMAIL_URL,
            json={"code": "123456"},
        )
        assert response.status_code == 422
