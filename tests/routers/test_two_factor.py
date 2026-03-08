"""
Router tests for 2FA endpoints under /auth/2fa/

Authentication strategy (same as profile tests):
  - Auth success: mock_redis.hgetall returns {"user_id": "1", "user_agent": "pytest"}
  - Auth fail (401): hgetall returns {} + DB returns None

References:
  - setup:    POST /auth/2fa/setup
  - confirm:  POST /auth/2fa/confirm
  - verify:   POST /auth/2fa/verify
  - disable:  POST /auth/2fa/disable
  - status:   GET  /auth/2fa/status
  - regen:    POST /auth/2fa/backup-codes/regenerate
"""
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from tests.routers.utils.response_asserts import assert_message_response

BEARER = "Bearer fake-2fa-test-token"
AUTH_HEADERS = {"Authorization": BEARER}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _setup_redis_hit(mock_redis):
    """Configure Redis to return a valid session (auth via cache)."""
    mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}


def _make_account(*, is_2fa_enabled=False, totp_secret_encrypted=None):
    """Return a mock Account for 2FA tests."""
    acc = MagicMock()
    acc.user_id = 1
    acc.user_name = "Test User"
    acc.email = "test@example.com"
    acc.password_hashed = "$2b$12$placeholder"
    acc.is_blocked = False
    acc.is_2fa_enabled = is_2fa_enabled
    acc.totp_secret_encrypted = totp_secret_encrypted
    return acc


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


def _db_scalar(value):
    """Return an execute result whose scalar() yields *value*."""
    r = MagicMock()
    r.scalar.return_value = value
    return r


# ═══════════════════════════════════════════════════════════════════════════════
#  POST /auth/2fa/setup
# ═══════════════════════════════════════════════════════════════════════════════

class TestSetup2FA:

    async def test_setup_success(self, client, mock_db, mock_redis):
        """User with 2FA disabled can successfully initiate setup."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=False)
        mock_db.execute.return_value = _db_result(account)

        response = await client.post("/auth/2fa/setup", headers=AUTH_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert "totp_uri" in body
        assert body["totp_uri"].startswith("otpauth://totp/")
        assert "qr_code_base64" in body
        assert body["qr_code_base64"].startswith("data:image/png;base64,")
        assert "backup_codes" in body
        assert len(body["backup_codes"]) == 8
        # Verify Redis was called to cache setup data
        mock_redis.set.assert_called_once()

    async def test_setup_conflict_already_enabled(self, client, mock_db, mock_redis):
        """Setup should return 409 if 2FA is already enabled."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=True)
        mock_db.execute.return_value = _db_result(account)

        response = await client.post("/auth/2fa/setup", headers=AUTH_HEADERS)

        assert response.status_code == 409
        assert response.json()["message"] == "2FA is already enabled"

    async def test_setup_unauthorized(self, client, mock_db, mock_redis):
        """Missing or invalid auth → 401."""
        response = await client.post("/auth/2fa/setup", headers={"Authorization": "Bearer bad"})

        assert response.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
#  POST /auth/2fa/confirm
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfirm2FA:

    @patch("src.routers.two_factor.verify_totp_code", return_value=True)
    @patch("src.routers.two_factor.encrypt_secret", return_value="encrypted_blob")
    async def test_confirm_success(self, mock_encrypt, mock_verify, client, mock_db, mock_redis):
        """Valid TOTP code confirms 2FA binding."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=False)
        mock_db.execute.return_value = _db_result(account)

        setup_data = json.dumps({"secret": "JBSWY3DPEHPK3PXP", "backup_codes": ["A1B2C3D4"] * 8})
        mock_redis.get.return_value = setup_data

        response = await client.post(
            "/auth/2fa/confirm", headers=AUTH_HEADERS, json={"code": "123456"}
        )

        assert response.status_code == 200
        assert response.json()["message"] == "2FA enabled successfully"
        assert account.is_2fa_enabled is True
        assert account.totp_secret_encrypted == "encrypted_blob"
        mock_redis.delete.assert_called()

    @patch("src.routers.two_factor.verify_totp_code", return_value=False)
    async def test_confirm_invalid_code(self, mock_verify, client, mock_db, mock_redis):
        """Wrong TOTP code → 400."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=False)
        mock_db.execute.return_value = _db_result(account)

        setup_data = json.dumps({"secret": "JBSWY3DPEHPK3PXP", "backup_codes": ["A1B2C3D4"] * 8})
        mock_redis.get.return_value = setup_data

        response = await client.post(
            "/auth/2fa/confirm", headers=AUTH_HEADERS, json={"code": "000000"}
        )

        assert response.status_code == 400
        assert response.json()["message"] == "Invalid TOTP code"

    async def test_confirm_no_setup_data(self, client, mock_db, mock_redis):
        """Confirm without prior setup → 400."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=False)
        mock_db.execute.return_value = _db_result(account)
        mock_redis.get.return_value = None  # no cached setup data

        response = await client.post(
            "/auth/2fa/confirm", headers=AUTH_HEADERS, json={"code": "123456"}
        )

        assert response.status_code == 400

    async def test_confirm_conflict_already_enabled(self, client, mock_db, mock_redis):
        """Confirm when 2FA already active → 409."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=True)
        mock_db.execute.return_value = _db_result(account)

        response = await client.post(
            "/auth/2fa/confirm", headers=AUTH_HEADERS, json={"code": "123456"}
        )

        assert response.status_code == 409


# ═══════════════════════════════════════════════════════════════════════════════
#  POST /auth/2fa/verify
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerify2FA:

    @patch("src.routers.two_factor.save_session", new_callable=AsyncMock)
    @patch("src.routers.two_factor.decrypt_secret", return_value="JBSWY3DPEHPK3PXP")
    @patch("src.routers.two_factor.verify_totp_code", return_value=True)
    @patch("src.routers.two_factor.hash_token", return_value="hashed_temp")
    async def test_verify_totp_success(
        self, mock_hash, mock_verify, mock_decrypt, mock_save, client, mock_db, mock_redis
    ):
        """Valid TOTP code → 200 with id, name, token."""
        temp_token_record = MagicMock()
        temp_token_record.user_id = 1
        temp_token_record.token_type = "2fa_verify"
        temp_token_record.expire_at = datetime.now(timezone.utc) + timedelta(minutes=5)

        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc_secret")

        mock_db.execute.side_effect = [
            _db_result(temp_token_record),  # TempToken lookup
            _db_result(account),            # Account lookup
        ]

        response = await client.post(
            "/auth/2fa/verify",
            headers={"Temp-Token": "temp-token-value"},
            json={"code": "123456"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == 1
        assert body["name"] == "Test User"
        assert isinstance(body["token"], str) and body["token"]

    @patch("src.routers.two_factor.save_session", new_callable=AsyncMock)
    @patch("src.routers.two_factor.verify_password", return_value=True)
    @patch("src.routers.two_factor.hash_token", return_value="hashed_temp")
    async def test_verify_backup_code_success(
        self, mock_hash, mock_verify_pw, mock_save, client, mock_db, mock_redis
    ):
        """Valid backup code → 200 with id, name, token."""
        temp_token_record = MagicMock()
        temp_token_record.user_id = 1
        temp_token_record.token_type = "2fa_verify"
        temp_token_record.expire_at = datetime.now(timezone.utc) + timedelta(minutes=5)

        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc_secret")

        backup_code = MagicMock()
        backup_code.user_id = 1
        backup_code.code_hashed = "$2b$12$placeholder"
        backup_code.is_used = False

        mock_db.execute.side_effect = [
            _db_result(temp_token_record),  # TempToken lookup
            _db_result(account),            # Account lookup
            _db_scalars_all([backup_code]), # backup codes lookup
        ]

        response = await client.post(
            "/auth/2fa/verify",
            headers={"Temp-Token": "temp-token-value"},
            json={"code": "A1B2C3D4"},  # 8-char hex = backup code format
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == 1
        assert body["name"] == "Test User"
        assert backup_code.is_used is True

    @patch("src.routers.two_factor.decrypt_secret", return_value="JBSWY3DPEHPK3PXP")
    @patch("src.routers.two_factor.verify_totp_code", return_value=False)
    @patch("src.routers.two_factor.hash_token", return_value="hashed_temp")
    async def test_verify_invalid_code(self, mock_hash, mock_verify, mock_decrypt, client, mock_db, mock_redis):
        """Wrong TOTP code → 401."""
        temp_token_record = MagicMock()
        temp_token_record.user_id = 1
        temp_token_record.token_type = "2fa_verify"
        temp_token_record.expire_at = datetime.now(timezone.utc) + timedelta(minutes=5)

        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc_secret")

        mock_db.execute.side_effect = [
            _db_result(temp_token_record),
            _db_result(account),
        ]

        response = await client.post(
            "/auth/2fa/verify",
            headers={"Temp-Token": "temp-token-value"},
            json={"code": "000000"},
        )

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid 2FA code"

    @patch("src.routers.two_factor.hash_token", return_value="hashed_temp")
    async def test_verify_invalid_temp_token(self, mock_hash, client, mock_db, mock_redis):
        """Non-existent temp token → 401."""
        mock_db.execute.return_value = _db_result(None)

        response = await client.post(
            "/auth/2fa/verify",
            headers={"Temp-Token": "bad-token"},
            json={"code": "123456"},
        )

        assert response.status_code == 401

    @patch("src.routers.two_factor.hash_token", return_value="hashed_temp")
    async def test_verify_expired_temp_token(self, mock_hash, client, mock_db, mock_redis):
        """Expired temp token → 401."""
        expired = MagicMock()
        expired.user_id = 1
        expired.token_type = "2fa_verify"
        expired.expire_at = datetime.now(timezone.utc) - timedelta(minutes=1)

        mock_db.execute.return_value = _db_result(expired)

        response = await client.post(
            "/auth/2fa/verify",
            headers={"Temp-Token": "expired-token"},
            json={"code": "123456"},
        )

        assert response.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
#  POST /auth/2fa/disable
# ═══════════════════════════════════════════════════════════════════════════════

class TestDisable2FA:

    @patch("src.routers.two_factor.verify_password", return_value=True)
    async def test_disable_success(self, mock_verify_pw, client, mock_db, mock_redis):
        """Correct password disables 2FA."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc")

        mock_db.execute.side_effect = [
            _db_result(account),       # _require_user → Account
            _db_scalars_all([]),        # backup codes query (empty)
        ]

        response = await client.post(
            "/auth/2fa/disable", headers=AUTH_HEADERS, json={"password": "Password1"}
        )

        assert response.status_code == 200
        assert response.json()["message"] == "2FA disabled successfully"
        assert account.is_2fa_enabled is False
        assert account.totp_secret_encrypted is None

    @patch("src.routers.two_factor.verify_password", return_value=False)
    async def test_disable_wrong_password(self, mock_verify_pw, client, mock_db, mock_redis):
        """Wrong password → 401."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc")
        mock_db.execute.return_value = _db_result(account)

        response = await client.post(
            "/auth/2fa/disable", headers=AUTH_HEADERS, json={"password": "wrong"}
        )

        assert response.status_code == 401
        assert response.json()["message"] == "Incorrect password"

    async def test_disable_not_enabled(self, client, mock_db, mock_redis):
        """Disable when 2FA is off → 400."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=False)
        mock_db.execute.return_value = _db_result(account)

        response = await client.post(
            "/auth/2fa/disable", headers=AUTH_HEADERS, json={"password": "Password1"}
        )

        assert response.status_code == 400
        assert response.json()["message"] == "2FA is not enabled"


# ═══════════════════════════════════════════════════════════════════════════════
#  GET /auth/2fa/status
# ═══════════════════════════════════════════════════════════════════════════════

class TestStatus2FA:

    async def test_status_enabled(self, client, mock_db, mock_redis):
        """2FA enabled → returns status with backup codes count."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=True)

        mock_db.execute.side_effect = [
            _db_result(account),   # _require_user → Account
            _db_scalar(5),         # count() of remaining backup codes
        ]

        response = await client.get("/auth/2fa/status", headers=AUTH_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["is_2fa_enabled"] is True
        assert body["backup_codes_remaining"] == 5

    async def test_status_disabled(self, client, mock_db, mock_redis):
        """2FA disabled → status with 0 backup codes."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=False)
        mock_db.execute.return_value = _db_result(account)

        response = await client.get("/auth/2fa/status", headers=AUTH_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["is_2fa_enabled"] is False
        assert body["backup_codes_remaining"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  POST /auth/2fa/backup-codes/regenerate
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegenerateBackupCodes:

    @patch("src.routers.two_factor.decrypt_secret", return_value="JBSWY3DPEHPK3PXP")
    @patch("src.routers.two_factor.verify_totp_code", return_value=True)
    async def test_regenerate_success(self, mock_verify, mock_decrypt, client, mock_db, mock_redis):
        """Valid TOTP code → new backup codes returned."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc")

        mock_db.execute.side_effect = [
            _db_result(account),       # _require_user → Account
            _db_scalars_all([]),        # old backup codes (delete)
        ]

        response = await client.post(
            "/auth/2fa/backup-codes/regenerate", headers=AUTH_HEADERS, json={"code": "123456"}
        )

        assert response.status_code == 200
        body = response.json()
        assert "backup_codes" in body
        assert len(body["backup_codes"]) == 8

    @patch("src.routers.two_factor.decrypt_secret", return_value="JBSWY3DPEHPK3PXP")
    @patch("src.routers.two_factor.verify_totp_code", return_value=False)
    async def test_regenerate_invalid_code(self, mock_verify, mock_decrypt, client, mock_db, mock_redis):
        """Wrong TOTP code → 400."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=True, totp_secret_encrypted="enc")
        mock_db.execute.return_value = _db_result(account)

        response = await client.post(
            "/auth/2fa/backup-codes/regenerate", headers=AUTH_HEADERS, json={"code": "000000"}
        )

        assert response.status_code == 400
        assert response.json()["message"] == "Invalid TOTP code"

    async def test_regenerate_2fa_not_enabled(self, client, mock_db, mock_redis):
        """2FA not enabled → 400."""
        _setup_redis_hit(mock_redis)
        account = _make_account(is_2fa_enabled=False)
        mock_db.execute.return_value = _db_result(account)

        response = await client.post(
            "/auth/2fa/backup-codes/regenerate", headers=AUTH_HEADERS, json={"code": "123456"}
        )

        assert response.status_code == 400
        assert response.json()["message"] == "2FA is not enabled"


# ═══════════════════════════════════════════════════════════════════════════════
#  Login → 2FA flow integration test
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogin2FAFlow:
    """Test that login returns requires_2fa when 2FA is enabled."""

    @patch("src.routers.auth.save_session", new_callable=AsyncMock)
    async def test_login_triggers_2fa(self, mock_save, client, mock_db, mock_redis):
        """User with 2FA enabled → login returns requires_2fa=True + temp_token."""
        from src.utils.password_utils import hash_password

        user = MagicMock()
        user.user_id = 1
        user.user_name = "Test User"
        user.email = "test@example.com"
        user.password_hashed = hash_password("Password1")
        user.is_blocked = False
        user.is_2fa_enabled = True

        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        response = await client.post(
            "/auth/login", json={"email": "test@example.com", "password": "Password1"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["requires_2fa"] is True
        assert isinstance(body["temp_token"], str) and body["temp_token"]
        assert body["token"] == ""
