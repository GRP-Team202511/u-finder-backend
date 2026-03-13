"""
Router tests for:
- POST /api/admin/users/{userId}/block
- POST /api/admin/users/{userId}/unblock
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.config.constants import UserType
from src.utils.jwt_utils import create_access_token
from tests.routers.utils.response_asserts import assert_message_response, assert_validation_error


BLOCK_URL = "/api/admin/users/{user_id}/block"
UNBLOCK_URL = "/api/admin/users/{user_id}/unblock"


def _make_account(
    *,
    user_id: int,
    user_name: str = "User",
    email: str = "user@example.com",
    user_type: int = UserType.STUDENT,
    is_blocked: bool = False,
    email_verified: bool = True,
):
    """Return a minimal mock Account object."""
    acc = MagicMock()
    acc.user_id = user_id
    acc.user_name = user_name
    acc.email = email
    acc.user_type = user_type
    acc.is_blocked = is_blocked
    acc.email_verified = email_verified
    acc.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return acc


def _admin_auth_header(user_id: int = 99) -> dict:
    """Return an Authorization header carrying a valid admin JWT."""
    token = create_access_token(
        data={"sub": str(user_id), "email": "admin@example.com", "user_type": UserType.ADMIN}
    )
    return {"Authorization": f"Bearer {token}"}


class TestAdminUserActionsAuth:
    async def test_block_missing_auth_header(self, client):
        """Missing Authorization header must return 422."""
        response = await client.post(BLOCK_URL.format(user_id=1))

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_unblock_invalid_token(self, client):
        """Invalid token must return 401."""
        response = await client.post(
            UNBLOCK_URL.format(user_id=1),
            headers={"Authorization": "Bearer invalid-token"},
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_block_non_admin_user(self, client, mock_db):
        """Non-admin caller must return 403."""
        caller = _make_account(user_id=100, user_type=UserType.STUDENT)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = caller
        mock_db.execute.return_value = r0

        response = await client.post(
            BLOCK_URL.format(user_id=1),
            headers=_admin_auth_header(user_id=100),
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Admin permission required")


class TestAdminUserActionsBlock:
    async def test_block_user_success(self, client, mock_db):
        """Admin can block a non-admin user and receive success."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target = _make_account(user_id=1, user_type=UserType.STUDENT, is_blocked=False)

        r0 = MagicMock()  # require_admin lookup
        r0.scalar_one_or_none.return_value = admin

        r1 = MagicMock()  # target lookup
        r1.scalar_one_or_none.return_value = target

        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            BLOCK_URL.format(user_id=1),
            headers=_admin_auth_header(),
        )

        assert response.status_code == 200
        assert response.json() == {"result": "success"}
        assert target.is_blocked is True
        mock_db.commit.assert_awaited_once()

    async def test_block_user_idempotent_when_already_blocked(self, client, mock_db):
        """Blocking an already blocked user must still return success."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target = _make_account(user_id=1, user_type=UserType.STUDENT, is_blocked=True)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin

        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target

        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            BLOCK_URL.format(user_id=1),
            headers=_admin_auth_header(),
        )

        assert response.status_code == 200
        assert response.json() == {"result": "success"}
        assert target.is_blocked is True
        mock_db.commit.assert_awaited_once()

    async def test_block_user_not_found(self, client, mock_db):
        """Unknown target user must return 404."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin

        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            BLOCK_URL.format(user_id=404),
            headers=_admin_auth_header(),
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "Resource not found")

    async def test_block_admin_account_forbidden(self, client, mock_db):
        """Blocking an admin account must return 403."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target_admin = _make_account(user_id=3, user_type=UserType.ADMIN)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin

        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target_admin

        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            BLOCK_URL.format(user_id=3),
            headers=_admin_auth_header(),
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Cannot block/unblock an admin account")


class TestAdminUserActionsUnblock:
    async def test_unblock_user_success(self, client, mock_db):
        """Admin can unblock a blocked non-admin user and receive success."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target = _make_account(user_id=1, user_type=UserType.STUDENT, is_blocked=True)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin

        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target

        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            UNBLOCK_URL.format(user_id=1),
            headers=_admin_auth_header(),
        )

        assert response.status_code == 200
        assert response.json() == {"result": "success"}
        assert target.is_blocked is False
        mock_db.commit.assert_awaited_once()

    async def test_unblock_user_idempotent_when_already_active(self, client, mock_db):
        """Unblocking an active user must still return success."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target = _make_account(user_id=1, user_type=UserType.STUDENT, is_blocked=False)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin

        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target

        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            UNBLOCK_URL.format(user_id=1),
            headers=_admin_auth_header(),
        )

        assert response.status_code == 200
        assert response.json() == {"result": "success"}
        assert target.is_blocked is False
        mock_db.commit.assert_awaited_once()

    async def test_unblock_user_not_found(self, client, mock_db):
        """Unknown target user must return 404."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin

        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            UNBLOCK_URL.format(user_id=404),
            headers=_admin_auth_header(),
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "Resource not found")

    async def test_unblock_admin_account_forbidden(self, client, mock_db):
        """Unblocking an admin account must return 403."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target_admin = _make_account(user_id=3, user_type=UserType.ADMIN)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin

        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target_admin

        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            UNBLOCK_URL.format(user_id=3),
            headers=_admin_auth_header(),
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Cannot block/unblock an admin account")
