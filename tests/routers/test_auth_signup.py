# This code was completed by GRP Team 2025.11.
"""
Router tests for:
  POST /auth/signup
  POST /auth/verify
  POST /auth/signup/resend
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

from src.utils.password_utils import hash_password
from tests.routers.utils.response_asserts import (
    assert_verify_signup_200,
    assert_message_response,
    assert_rate_limit_response,
    assert_signup_200,
    assert_token_invalid_response,
    assert_validation_error,
    assert_wrong_code_response,
)


# ── Constants ─────────────────────────────────────────────────────────────────

SIGNUP_URL = "/auth/signup"
VERIFY_URL = "/auth/verify"
RESEND_URL = "/auth/signup/resend"

VALID_SIGNUP_PAYLOAD = {
    "name": "Test User",
    "email": "test@example.com",
    "password": "Password1",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_account(
    *,
    user_id: int = 1,
    email: str = "test@example.com",
    user_name: str = "Test User",
    is_blocked: bool = False,
    email_verified: bool = False,
    profile=None,
):
    acc = MagicMock()
    acc.user_id = user_id
    acc.email = email
    acc.user_name = user_name
    acc.is_blocked = is_blocked
    acc.email_verified = email_verified
    acc.profile = profile
    return acc


def _make_temp_token(
    *,
    token_type: str = "email_verify",
    code: str = "123456",
    expire_at=None,
    created_at=None,
):
    """Build a mock TempToken with a bcrypt-hashed verification code."""
    token = MagicMock()
    token.id = 1
    token.user_id = 1
    token.token_hashed = "fake-temp-token"
    token.token_type = token_type
    token.expire_at = expire_at or datetime.now(timezone.utc) + timedelta(hours=24)
    token.created_at = created_at or datetime.now(timezone.utc) - timedelta(seconds=120)
    token.verification_code_hashed = hash_password(code)
    return token


def _two_results(first, second):
    """Return a side_effect list for two sequential db.execute() calls."""
    r1, r2 = MagicMock(), MagicMock()
    r1.scalar_one_or_none.return_value = first
    r2.scalar_one_or_none.return_value = second
    return [r1, r2]


# ── POST /auth/signup ─────────────────────────────────────────────────────────

class TestSignup:
    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock, return_value=True)
    async def test_signup_success(self, mock_email, client, mock_db):
        """Valid signup returns 200 with a temp_token string."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None  # no existing account

        response = await client.post(SIGNUP_URL, json=VALID_SIGNUP_PAYLOAD)

        assert response.status_code == 200
        assert_signup_200(response.json())

    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock, return_value=True)
    async def test_signup_duplicate_verified_email(self, mock_email, client, mock_db):
        """Verified email must return 409 with 'Account exists'."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = _make_account(email_verified=True)

        response = await client.post(SIGNUP_URL, json=VALID_SIGNUP_PAYLOAD)

        assert response.status_code == 409
        assert_message_response(response.json(), "Account exists")

    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock, return_value=True)
    async def test_signup_unverified_email_allows_re_registration(self, mock_email, client, mock_db):
        """Unverified email must allow re-registration and return 200 with a new temp_token."""
        unverified_account = _make_account(email_verified=False)
        # First execute returns the unverified account, second is the bulk DELETE (no result needed)
        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = unverified_account
        result2 = MagicMock()  # bulk delete result
        mock_db.execute.side_effect = [result1, result2]

        response = await client.post(SIGNUP_URL, json=VALID_SIGNUP_PAYLOAD)

        assert response.status_code == 200
        assert_signup_200(response.json())

    async def test_signup_weak_password_no_digit(self, client):
        """Password with no digits must be rejected with 422."""
        response = await client.post(
            SIGNUP_URL, json={**VALID_SIGNUP_PAYLOAD, "password": "OnlyLetters"}
        )
        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_signup_weak_password_no_letter(self, client):
        """Password with only digits must be rejected with 422."""
        response = await client.post(
            SIGNUP_URL, json={**VALID_SIGNUP_PAYLOAD, "password": "12345678"}
        )
        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_signup_invalid_email(self, client):
        """Malformed email must be rejected with 422."""
        response = await client.post(
            SIGNUP_URL, json={**VALID_SIGNUP_PAYLOAD, "email": "not-an-email"}
        )
        assert response.status_code == 422
        assert_validation_error(response.json())

    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock, return_value=True)
    async def test_signup_email_normalised_to_lowercase(self, mock_email, client, mock_db):
        """Mixed-case email must be stored as lowercase (no duplicate conflict)."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.post(
            SIGNUP_URL, json={**VALID_SIGNUP_PAYLOAD, "email": "Test@Example.COM"}
        )

        assert response.status_code == 200
        assert_signup_200(response.json())


# ── POST /auth/verify ─────────────────────────────────────────────────────────

class TestVerifySignupEmail:
    async def test_verify_success(self, client, mock_db):
        """Correct code + valid token must return 201 with id, name, and token."""
        code = "123456"
        token_record = _make_temp_token(code=code)
        user = _make_account(is_blocked=True)
        mock_db.execute.side_effect = _two_results(token_record, user)

        response = await client.post(
            VERIFY_URL,
            json={"code": code},
            headers={"Temp-Token": "fake-temp-token"},
        )

        assert response.status_code == 201
        body = response.json()
        assert_verify_signup_200(body)
        assert body["id"] == user.user_id
        assert body["name"] == user.user_name

    async def test_verify_success_with_existing_profile(self, client, mock_db):
        """Re-verified user with existing profile must not create duplicate profile."""
        code = "123456"
        token_record = _make_temp_token(code=code)
        existing_profile = MagicMock()  # simulate profile already exists
        user = _make_account(profile=existing_profile)
        mock_db.execute.side_effect = _two_results(token_record, user)

        response = await client.post(
            VERIFY_URL,
            json={"code": code},
            headers={"Temp-Token": "fake-temp-token"},
        )

        assert response.status_code == 201
        body = response.json()
        assert_verify_signup_200(body)
        # db.add should NOT be called for UserProfile since profile already exists
        add_calls = [c for c in mock_db.add.call_args_list
                     if hasattr(c[0][0], 'basic_info')]  # UserProfile has basic_info
        assert len(add_calls) == 0

    async def test_verify_invalid_temp_token(self, client, mock_db):
        """Token not found in DB must return 401."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.post(
            VERIFY_URL,
            json={"code": "123456"},
            headers={"Temp-Token": "non-existent-token"},
        )

        assert response.status_code == 401
        assert_wrong_code_response(response.json())

    async def test_verify_expired_token(self, client, mock_db):
        """Expired temp token must return 401."""
        expired = _make_temp_token(expire_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        mock_db.execute.return_value.scalar_one_or_none.return_value = expired

        response = await client.post(
            VERIFY_URL,
            json={"code": "123456"},
            headers={"Temp-Token": "some-token"},
        )

        assert response.status_code == 401
        assert_wrong_code_response(response.json())

    async def test_verify_wrong_code(self, client, mock_db):
        """Mismatched verification code must return 401."""
        token_record = _make_temp_token(code="123456")
        mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

        response = await client.post(
            VERIFY_URL,
            json={"code": "999999"},
            headers={"Temp-Token": "fake-temp-token"},
        )

        assert response.status_code == 401
        assert_wrong_code_response(response.json())

    async def test_verify_user_not_found(self, client, mock_db):
        """Valid token/code but missing Account record must return 404."""
        code = "123456"
        token_record = _make_temp_token(code=code)
        mock_db.execute.side_effect = _two_results(token_record, None)

        response = await client.post(
            VERIFY_URL,
            json={"code": code},
            headers={"Temp-Token": "fake-temp-token"},
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "User not found")


# ── POST /auth/signup/resend ──────────────────────────────────────────────────

class TestResendSignupCode:
    @patch("src.routers.auth.send_verification_email", new_callable=AsyncMock, return_value=True)
    async def test_resend_success(self, mock_email, client, mock_db):
        """Valid token outside rate-limit window must return 200."""
        token_record = _make_temp_token(
            created_at=datetime.now(timezone.utc) - timedelta(seconds=120)  # 2 min ago
        )
        user = _make_account()
        mock_db.execute.side_effect = _two_results(token_record, user)

        response = await client.post(RESEND_URL, headers={"Temp-Token": "fake-temp-token"})

        assert response.status_code == 200
        assert_message_response(response.json(), "Verification code resent successfully")

    async def test_resend_invalid_token(self, client, mock_db):
        """Unknown token must return 401."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.post(RESEND_URL, headers={"Temp-Token": "invalid-token"})

        assert response.status_code == 401
        assert_token_invalid_response(response.json())

    async def test_resend_expired_token(self, client, mock_db):
        """Expired token must return 401."""
        expired = _make_temp_token(expire_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        mock_db.execute.return_value.scalar_one_or_none.return_value = expired

        response = await client.post(RESEND_URL, headers={"Temp-Token": "fake-temp-token"})

        assert response.status_code == 401
        assert_token_invalid_response(response.json())

    async def test_resend_rate_limited(self, client, mock_db):
        """Request within 60 s of last send must return 429 with retryAfter."""
        token_record = _make_temp_token(
            created_at=datetime.now(timezone.utc) - timedelta(seconds=10)  # only 10 s ago
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

        response = await client.post(RESEND_URL, headers={"Temp-Token": "fake-temp-token"})

        assert response.status_code == 429
        assert_rate_limit_response(response.json())
