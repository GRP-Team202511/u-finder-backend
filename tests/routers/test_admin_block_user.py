"""
Router tests for POST /api/admin/users/{userId}/block (Block User)

Authentication strategy:
  - Successful auth: create a real JWT via create_access_token() and mock
    the DB call inside require_admin to return an admin account.
  - Failed auth (401): use an invalid/missing Bearer token.
  - Non-admin (403): mock the DB to return a non-admin account.

Multiple sequential DB calls are handled via mock_db.execute.side_effect.
"""
from unittest.mock import MagicMock
from datetime import datetime, timezone

from src.config.constants import UserType
from src.utils.jwt_utils import create_access_token
from tests.routers.utils.response_asserts import assert_message_response

BLOCK_URL = "/api/admin/users/{userId}/block"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db_result(value):
    """Return a MagicMock whose scalar_one_or_none() yields the given value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_admin_account(
    *,
    user_id: int = 99,
    user_name: str = "Admin User",
    email: str = "admin@example.com",
    user_type: int = UserType.ADMIN,
    is_blocked: bool = False,
    email_verified: bool = True,
):
    """Return a minimal mock Account for require_admin."""
    acc = MagicMock()
    acc.user_id = user_id
    acc.user_name = user_name
    acc.email = email
    acc.user_type = user_type
    acc.is_blocked = is_blocked
    acc.email_verified = email_verified
    acc.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return acc


def _make_target_user(user_id: int = 5, *, user_type: int = UserType.STUDENT, is_blocked: bool = False):
    """Return a mock Account representing the user to be blocked."""
    acc = MagicMock()
    acc.user_id = user_id
    acc.user_name = f"User{user_id}"
    acc.email = f"user{user_id}@test.com"
    acc.user_type = user_type
    acc.is_blocked = is_blocked
    acc.email_verified = True
    acc.created_at = datetime(2026, 2, 15, tzinfo=timezone.utc)
    return acc


def _admin_auth_header(user_id: int = 99) -> dict:
    """Return a Bearer header carrying a real JWT for the given admin user."""
    token = create_access_token(
        data={"sub": str(user_id), "email": "admin@example.com", "user_type": UserType.ADMIN}
    )
    return {"Authorization": f"Bearer {token}"}


# ── POST /api/admin/users/{userId}/block Tests ────────────────────────────────

class TestBlockUser:

    async def test_block_user_success(self, client, mock_db):
        """Admin blocks an active user -> 200 with success result."""
        admin = _make_admin_account()
        target = _make_target_user(user_id=5)

        mock_db.execute.side_effect = [
            _make_db_result(admin),   # require_admin: account lookup
            _make_db_result(target),  # _get_target_non_admin: find target
        ]

        response = await client.post(
            BLOCK_URL.format(userId=5), headers=_admin_auth_header()
        )

        assert response.status_code == 200
        body = response.json()
        assert body["result"] == "success"

        assert target.is_blocked is True
        mock_db.commit.assert_called_once()

    async def test_block_already_blocked_user_idempotent(self, client, mock_db):
        """Blocking an already-blocked user still returns 200."""
        admin = _make_admin_account()
        target = _make_target_user(user_id=5, is_blocked=True)

        mock_db.execute.side_effect = [
            _make_db_result(admin),
            _make_db_result(target),
        ]

        response = await client.post(
            BLOCK_URL.format(userId=5), headers=_admin_auth_header()
        )

        assert response.status_code == 200
        assert response.json()["result"] == "success"

    async def test_block_admin_account_forbidden(self, client, mock_db):
        """Attempting to block another admin -> 403."""
        admin = _make_admin_account()
        target_admin = _make_target_user(user_id=10, user_type=UserType.ADMIN)

        mock_db.execute.side_effect = [
            _make_db_result(admin),
            _make_db_result(target_admin),
        ]

        response = await client.post(
            BLOCK_URL.format(userId=10), headers=_admin_auth_header()
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Cannot block/unblock an admin account")

    async def test_block_user_not_found(self, client, mock_db):
        """Blocking a non-existent user -> 404."""
        admin = _make_admin_account()

        mock_db.execute.side_effect = [
            _make_db_result(admin),
            _make_db_result(None),
        ]

        response = await client.post(
            BLOCK_URL.format(userId=999), headers=_admin_auth_header()
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "User not found")

    async def test_block_user_missing_auth_header(self, client):
        """Missing Authorization header -> 422."""
        response = await client.post(BLOCK_URL.format(userId=5))
        assert response.status_code == 422

    async def test_block_user_invalid_token(self, client, mock_db):
        """Invalid Bearer token -> 401."""
        response = await client.post(
            BLOCK_URL.format(userId=5),
            headers={"Authorization": "Bearer invalid-token"},
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_block_user_non_admin(self, client, mock_db):
        """Valid token but user_type=1 (student) -> 403."""
        student = _make_admin_account(user_type=UserType.STUDENT)
        mock_db.execute.return_value = _make_db_result(student)

        response = await client.post(
            BLOCK_URL.format(userId=5), headers=_admin_auth_header()
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Admin permission required")

    async def test_block_user_response_fields(self, client, mock_db):
        """Verify response contains only the 'result' field."""
        admin = _make_admin_account()
        target = _make_target_user(user_id=10)

        mock_db.execute.side_effect = [
            _make_db_result(admin),
            _make_db_result(target),
        ]

        response = await client.post(
            BLOCK_URL.format(userId=10), headers=_admin_auth_header()
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"result"}
        assert body["result"] == "success"
