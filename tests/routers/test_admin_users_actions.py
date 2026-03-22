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
    user_type: int = UserType.USER,
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


def _auth_header(user_id: int = 99, user_type: int = UserType.ADMIN) -> dict:
    """Return an Authorization header carrying a valid admin JWT."""
    token = create_access_token(
        data={"sub": str(user_id), "email": "admin@example.com", "user_type": user_type}
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
        caller = _make_account(user_id=100, user_type=UserType.USER)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = caller
        mock_db.execute.return_value = r0

        response = await client.post(
            BLOCK_URL.format(user_id=1),
            headers=_auth_header(user_id=100),
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Admin permission required")


class TestAdminUserActionsBlock:
    async def test_block_user_success(self, client, mock_db):
        """Admin can block a non-admin user and receive success."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target = _make_account(user_id=1, user_type=UserType.USER, is_blocked=False)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            BLOCK_URL.format(user_id=1), headers=_auth_header(),
        )

        assert response.status_code == 200
        assert response.json() == {"result": "success"}
        assert target.is_blocked is True
        mock_db.commit.assert_awaited_once()

    async def test_block_user_idempotent_when_already_blocked(self, client, mock_db):
        """Blocking an already blocked user must still return success."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target = _make_account(user_id=1, user_type=UserType.USER, is_blocked=True)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            BLOCK_URL.format(user_id=1), headers=_auth_header(),
        )

        assert response.status_code == 200
        assert target.is_blocked is True

    async def test_block_user_not_found(self, client, mock_db):
        """Unknown target user must return 404."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            BLOCK_URL.format(user_id=404), headers=_auth_header(),
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "Resource not found")

    async def test_admin_cannot_block_admin(self, client, mock_db):
        """Admin blocking another admin account must return 403."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target_admin = _make_account(user_id=3, user_type=UserType.ADMIN)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target_admin
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            BLOCK_URL.format(user_id=3), headers=_auth_header(),
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Cannot block/unblock an admin account")

    async def test_super_admin_can_block_admin(self, client, mock_db):
        """Super admin can block an admin account -> 200."""
        sa = _make_account(user_id=1, user_type=UserType.SUPER_ADMIN)
        target_admin = _make_account(user_id=3, user_type=UserType.ADMIN)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = sa
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target_admin
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            BLOCK_URL.format(user_id=3),
            headers=_auth_header(user_id=1, user_type=UserType.SUPER_ADMIN),
        )

        assert response.status_code == 200
        assert target_admin.is_blocked is True

    async def test_cannot_block_super_admin(self, client, mock_db):
        """No one can block a super admin -> 403."""
        sa = _make_account(user_id=1, user_type=UserType.SUPER_ADMIN)
        target_sa = _make_account(user_id=2, user_type=UserType.SUPER_ADMIN, email="sa2@example.com")

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = sa
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target_sa
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            BLOCK_URL.format(user_id=2),
            headers=_auth_header(user_id=1, user_type=UserType.SUPER_ADMIN),
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Cannot block/unblock a super admin account")


class TestAdminUserActionsUnblock:
    async def test_unblock_user_success(self, client, mock_db):
        """Admin can unblock a blocked non-admin user and receive success."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target = _make_account(user_id=1, user_type=UserType.USER, is_blocked=True)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            UNBLOCK_URL.format(user_id=1), headers=_auth_header(),
        )

        assert response.status_code == 200
        assert response.json() == {"result": "success"}
        assert target.is_blocked is False

    async def test_unblock_user_idempotent_when_already_active(self, client, mock_db):
        """Unblocking an active user must still return success."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target = _make_account(user_id=1, user_type=UserType.USER, is_blocked=False)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            UNBLOCK_URL.format(user_id=1), headers=_auth_header(),
        )

        assert response.status_code == 200
        assert target.is_blocked is False

    async def test_unblock_user_not_found(self, client, mock_db):
        """Unknown target user must return 404."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            UNBLOCK_URL.format(user_id=404), headers=_auth_header(),
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "Resource not found")

    async def test_admin_cannot_unblock_admin(self, client, mock_db):
        """Unblocking an admin account by a regular admin must return 403."""
        admin = _make_account(user_id=99, user_type=UserType.ADMIN)
        target_admin = _make_account(user_id=3, user_type=UserType.ADMIN)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target_admin
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            UNBLOCK_URL.format(user_id=3), headers=_auth_header(),
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Cannot block/unblock an admin account")

    async def test_super_admin_can_unblock_admin(self, client, mock_db):
        """Super admin can unblock an admin account -> 200."""
        sa = _make_account(user_id=1, user_type=UserType.SUPER_ADMIN)
        target_admin = _make_account(user_id=3, user_type=UserType.ADMIN, is_blocked=True)

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = sa
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target_admin
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            UNBLOCK_URL.format(user_id=3),
            headers=_auth_header(user_id=1, user_type=UserType.SUPER_ADMIN),
        )

        assert response.status_code == 200
        assert target_admin.is_blocked is False

    async def test_cannot_unblock_super_admin(self, client, mock_db):
        """No one can unblock a super admin -> 403."""
        sa = _make_account(user_id=1, user_type=UserType.SUPER_ADMIN)
        target_sa = _make_account(user_id=2, user_type=UserType.SUPER_ADMIN, email="sa2@example.com")

        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = sa
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = target_sa
        mock_db.execute.side_effect = [r0, r1]

        response = await client.post(
            UNBLOCK_URL.format(user_id=2),
            headers=_auth_header(user_id=1, user_type=UserType.SUPER_ADMIN),
        )

        assert response.status_code == 403
        assert_message_response(response.json(), "Cannot block/unblock a super admin account")
