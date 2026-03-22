"""
Router tests for DELETE /api/admin/users/{user_id} (Delete User)

Authentication strategy:
  - Successful auth: create a real JWT via create_access_token() and mock
    the DB call inside require_admin to return an admin account.
  - Failed auth (401): use an invalid/missing Bearer token.
  - Non-admin (403): mock the DB to return a non-admin account.

Multiple sequential DB calls are handled via mock_db.execute.side_effect.
"""
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from src.config.constants import UserType
from src.utils.jwt_utils import create_access_token
from tests.routers.utils.response_asserts import assert_message_response

DELETE_URL = "/api/admin/users/{userId}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db_result(value):
    """Return a MagicMock whose scalar_one_or_none() yields the given value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_account(
    *,
    user_id: int = 99,
    user_name: str = "Admin User",
    email: str = "admin@example.com",
    user_type: int = UserType.ADMIN,
    is_blocked: bool = False,
    email_verified: bool = True,
):
    """Return a minimal mock Account."""
    acc = MagicMock()
    acc.user_id = user_id
    acc.user_name = user_name
    acc.email = email
    acc.user_type = user_type
    acc.is_blocked = is_blocked
    acc.email_verified = email_verified
    acc.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return acc


def _make_target_user(user_id: int = 5, user_name: str = "Target User"):
    """Return a mock Account representing the user to be deleted."""
    acc = MagicMock()
    acc.user_id = user_id
    acc.user_name = user_name
    acc.email = f"user{user_id}@test.com"
    acc.user_type = UserType.USER
    acc.is_blocked = False
    acc.email_verified = True
    acc.created_at = datetime(2026, 2, 15, tzinfo=timezone.utc)
    return acc


def _auth_header(user_id: int = 99, user_type: int = UserType.ADMIN) -> dict:
    """Return a Bearer header carrying a real JWT."""
    token = create_access_token(
        data={"sub": str(user_id), "email": "admin@example.com", "user_type": user_type}
    )
    return {"Authorization": f"Bearer {token}"}


# ── DELETE /api/admin/users/{user_id} Tests ───────────────────────────────────

class TestDeleteUser:

    @patch("src.routers.admin._cleanup_avatar_files")
    async def test_delete_user_success(self, mock_cleanup, client, mock_db):
        """Admin deletes a regular user -> 200 with success result."""
        admin = _make_account()
        target = _make_target_user(user_id=5)

        mock_db.execute.side_effect = [
            _make_db_result(admin),
            _make_db_result(target),
        ]

        response = await client.delete(
            DELETE_URL.format(userId=5), headers=_auth_header()
        )

        assert response.status_code == 200
        assert response.json()["result"] == "success"
        mock_db.delete.assert_called_once_with(target)
        mock_db.commit.assert_called_once()
        mock_cleanup.assert_called_once_with(5)

    async def test_delete_user_self_deletion_forbidden(self, client, mock_db):
        """Admin tries to delete own account -> 403."""
        admin = _make_account(user_id=99)
        mock_db.execute.return_value = _make_db_result(admin)

        response = await client.delete(
            DELETE_URL.format(userId=99), headers=_auth_header(user_id=99)
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Cannot delete your own account")

    async def test_admin_cannot_delete_admin(self, client, mock_db):
        """Admin tries to delete another admin -> 403."""
        admin = _make_account(user_id=99)
        target_admin = _make_account(user_id=50, email="other_admin@example.com")

        mock_db.execute.side_effect = [
            _make_db_result(admin),
            _make_db_result(target_admin),
        ]

        response = await client.delete(
            DELETE_URL.format(userId=50), headers=_auth_header()
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Cannot delete an admin account")
        mock_db.delete.assert_not_called()

    @patch("src.routers.admin._cleanup_avatar_files")
    async def test_super_admin_can_delete_admin(self, mock_cleanup, client, mock_db):
        """Super admin can delete an admin account -> 200."""
        sa = _make_account(user_id=1, user_type=UserType.SUPER_ADMIN)
        target_admin = _make_account(user_id=50, email="admin2@example.com")

        mock_db.execute.side_effect = [
            _make_db_result(sa),
            _make_db_result(target_admin),
        ]

        response = await client.delete(
            DELETE_URL.format(userId=50),
            headers=_auth_header(user_id=1, user_type=UserType.SUPER_ADMIN),
        )

        assert response.status_code == 200
        assert response.json()["result"] == "success"
        mock_db.delete.assert_called_once_with(target_admin)

    async def test_super_admin_cannot_delete_super_admin(self, client, mock_db):
        """Super admin tries to delete another super admin -> 403."""
        sa = _make_account(user_id=1, user_type=UserType.SUPER_ADMIN)
        target_sa = _make_account(user_id=2, user_type=UserType.SUPER_ADMIN, email="sa2@example.com")

        mock_db.execute.side_effect = [
            _make_db_result(sa),
            _make_db_result(target_sa),
        ]

        response = await client.delete(
            DELETE_URL.format(userId=2),
            headers=_auth_header(user_id=1, user_type=UserType.SUPER_ADMIN),
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Cannot delete a super admin account")
        mock_db.delete.assert_not_called()

    @patch("src.routers.admin._cleanup_avatar_files")
    async def test_delete_user_not_found(self, mock_cleanup, client, mock_db):
        """Admin deletes non-existent user -> 404."""
        admin = _make_account()
        mock_db.execute.side_effect = [
            _make_db_result(admin),
            _make_db_result(None),
        ]

        response = await client.delete(
            DELETE_URL.format(userId=999), headers=_auth_header()
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "User not found")
        mock_db.delete.assert_not_called()
        mock_cleanup.assert_not_called()

    async def test_delete_user_missing_auth_header(self, client):
        """Missing Authorization header -> 422."""
        response = await client.delete(DELETE_URL.format(userId=5))
        assert response.status_code == 422

    async def test_delete_user_invalid_token(self, client, mock_db):
        """Invalid Bearer token -> 401."""
        response = await client.delete(
            DELETE_URL.format(userId=5),
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_delete_user_non_admin(self, client, mock_db):
        """Valid token but user_type=1 (user) -> 403."""
        regular = _make_account(user_type=UserType.USER)
        mock_db.execute.return_value = _make_db_result(regular)

        response = await client.delete(
            DELETE_URL.format(userId=5), headers=_auth_header()
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Admin permission required")

    async def test_delete_user_account_not_found_in_auth(self, client, mock_db):
        """Valid token but admin account deleted from DB -> 401."""
        mock_db.execute.return_value = _make_db_result(None)

        response = await client.delete(
            DELETE_URL.format(userId=5), headers=_auth_header()
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    @patch("src.routers.admin._cleanup_avatar_files")
    async def test_delete_user_response_fields(self, mock_cleanup, client, mock_db):
        """Verify response contains only the 'result' field."""
        admin = _make_account()
        target = _make_target_user(user_id=10)

        mock_db.execute.side_effect = [
            _make_db_result(admin),
            _make_db_result(target),
        ]

        response = await client.delete(
            DELETE_URL.format(userId=10), headers=_auth_header()
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"result"}
        assert body["result"] == "success"
