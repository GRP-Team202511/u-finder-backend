"""
Router tests for POST /api/admin/auth/login
"""
from unittest.mock import MagicMock
from src.config.constants import UserType
from src.utils.password_utils import hash_password
from tests.routers.utils.response_asserts import (
    assert_admin_login_200,
    assert_message_response,
    assert_validation_error,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_admin(
    *,
    password: str = "AdminPass1",
    is_blocked: bool = False,
    user_type: int = UserType.ADMIN,
    user_id: int = 99,
    user_name: str = "Admin User",
    email: str = "admin@example.com",
):
    """Return a minimal mock Account object for admin login tests."""
    user = MagicMock()
    user.user_id = user_id
    user.user_name = user_name
    user.email = email
    user.password_hashed = hash_password(password)
    user.user_type = user_type
    user.is_blocked = is_blocked
    return user


LOGIN_URL = "/api/admin/auth/login"
VALID_PAYLOAD = {"email": "admin@example.com", "password": "AdminPass1"}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAdminLogin:
    async def test_admin_login_success(self, client, mock_db):
        """Valid admin credentials must return 200 with id, name, and token."""
        admin = _make_admin()
        mock_db.execute.return_value.scalar_one_or_none.return_value = admin

        response = await client.post(LOGIN_URL, json=VALID_PAYLOAD)

        assert response.status_code == 200
        body = response.json()
        assert_admin_login_200(body)
        assert body["id"] == admin.user_id
        assert body["name"] == admin.user_name

    async def test_admin_login_user_not_found(self, client, mock_db):
        """Unknown email must return 401."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.post(LOGIN_URL, json=VALID_PAYLOAD)

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid email or password")

    async def test_admin_login_wrong_password(self, client, mock_db):
        """Incorrect password must return 401."""
        admin = _make_admin(password="CorrectPass1")
        mock_db.execute.return_value.scalar_one_or_none.return_value = admin

        response = await client.post(
            LOGIN_URL, json={"email": "admin@example.com", "password": "WrongPass1"}
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid email or password")

    async def test_admin_login_returns_user_type(self, client, mock_db):
        """Login response must include user_type field."""
        admin = _make_admin()
        mock_db.execute.return_value.scalar_one_or_none.return_value = admin

        response = await client.post(LOGIN_URL, json=VALID_PAYLOAD)

        assert response.status_code == 200
        body = response.json()
        assert body["user_type"] == UserType.ADMIN

    async def test_super_admin_login_success(self, client, mock_db):
        """Super admin credentials must return 200 with user_type=4."""
        sa = _make_admin(user_type=UserType.SUPER_ADMIN)
        mock_db.execute.return_value.scalar_one_or_none.return_value = sa

        response = await client.post(LOGIN_URL, json=VALID_PAYLOAD)

        assert response.status_code == 200
        body = response.json()
        assert_admin_login_200(body)
        assert body["user_type"] == UserType.SUPER_ADMIN

    async def test_admin_login_not_admin_user(self, client, mock_db):
        """A non-admin user (user_type not in [3, 4]) must return 403."""
        regular_user = _make_admin(user_type=UserType.USER)
        mock_db.execute.return_value.scalar_one_or_none.return_value = regular_user

        response = await client.post(LOGIN_URL, json=VALID_PAYLOAD)

        assert response.status_code == 403
        assert_message_response(response.json(), "Admin permission required")

    async def test_admin_login_blocked_account(self, client, mock_db):
        """A blocked admin account must return 403."""
        admin = _make_admin(is_blocked=True)
        mock_db.execute.return_value.scalar_one_or_none.return_value = admin

        response = await client.post(LOGIN_URL, json=VALID_PAYLOAD)

        assert response.status_code == 403
        assert_message_response(response.json(), "Account is blocked")

    async def test_admin_login_invalid_email_format(self, client):
        """A malformed email must return 422 (Pydantic validation)."""
        response = await client.post(
            LOGIN_URL, json={"email": "not-an-email", "password": "AdminPass1"}
        )

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_admin_login_missing_password(self, client):
        """Missing password field must return 422."""
        response = await client.post(LOGIN_URL, json={"email": "admin@example.com"})

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_admin_login_missing_email(self, client):
        """Missing email field must return 422."""
        response = await client.post(LOGIN_URL, json={"password": "AdminPass1"})

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_admin_login_email_case_insensitive(self, client, mock_db):
        """Email lookup must be case-insensitive (normalised to lowercase)."""
        admin = _make_admin(email="admin@example.com")
        mock_db.execute.return_value.scalar_one_or_none.return_value = admin

        response = await client.post(
            LOGIN_URL, json={"email": "ADMIN@EXAMPLE.COM", "password": "AdminPass1"}
        )

        assert response.status_code == 200
        body = response.json()
        assert_admin_login_200(body)
        assert body["id"] == admin.user_id
