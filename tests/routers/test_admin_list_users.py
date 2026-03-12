"""
Router tests for GET /admin/users (List Users)

Authentication strategy:
  - Successful auth: set mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}
    so that get_session() finds a Redis hit and returns user_id=1 without touching the DB.
  - Failed auth (401): leave hgetall returning {} (falsy) and DB returning None,
    so _get_current_user_id raises HTTP 401.

Admin permission:
  - Admin user: account.user_type = 3
  - Non-admin user: account.user_type = 1 (student) -> 403

Multiple sequential DB calls are handled via mock_db.execute.side_effect.
"""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

GET_URL = "/admin/users"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db_result(value):
    """Return a MagicMock whose scalar_one_or_none() yields the given value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_db_scalars_result(values):
    """Return a MagicMock whose scalars().all() yields the given list."""
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result = MagicMock()
    result.scalars.return_value = scalars_mock
    return result


def _setup_redis_hit(mock_redis):
    """Configure Redis to return a valid session (auth succeeds via cache)."""
    mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}


def _make_fake_admin():
    """Create a mock admin account (user_type=3)."""
    account = MagicMock()
    account.user_id = 1
    account.user_name = "Admin User"
    account.email = "admin@ufinder.com"
    account.user_type = 3
    account.is_blocked = False
    account.email_verified = True
    account.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return account


def _make_fake_user(user_id, name, email, user_type=1, is_blocked=False, email_verified=True):
    """Create a mock user account with customizable fields."""
    account = MagicMock()
    account.user_id = user_id
    account.user_name = name
    account.email = email
    account.user_type = user_type
    account.is_blocked = is_blocked
    account.email_verified = email_verified
    account.created_at = datetime(2026, 2, 15, tzinfo=timezone.utc)
    return account


# ── GET /admin/users Tests ────────────────────────────────────────────────────

class TestListUsers:

    async def test_list_users_success(self, client, mock_db, mock_redis, auth_headers):
        """Admin token + admin account -> 200 with user list."""
        _setup_redis_hit(mock_redis)

        admin = _make_fake_admin()
        user1 = _make_fake_user(2, "Alice", "alice@test.com", user_type=1, is_blocked=False, email_verified=True)
        user2 = _make_fake_user(3, "Bot03", "bot@temp.com", user_type=1, is_blocked=True, email_verified=True)
        user3 = _make_fake_user(4, "NewUser", "new@test.com", user_type=2, is_blocked=False, email_verified=False)

        mock_db.execute.side_effect = [
            _make_db_result(admin),           # Admin permission check
            _make_db_scalars_result([admin, user1, user2, user3]),  # Fetch all users
        ]

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 4

        # Verify admin user
        assert body[0]["id"] == 1
        assert body[0]["name"] == "Admin User"
        assert body[0]["type"] == "3"
        assert body[0]["status"] == "active"
        assert body[0]["available_actions"] == ["block", "delete"]

        # Verify active user
        assert body[1]["id"] == 2
        assert body[1]["status"] == "active"
        assert body[1]["available_actions"] == ["block", "delete"]

        # Verify blocked user
        assert body[2]["id"] == 3
        assert body[2]["status"] == "blocked"
        assert body[2]["available_actions"] == ["unblock", "delete"]

        # Verify pending user (email not verified)
        assert body[3]["id"] == 4
        assert body[3]["status"] == "pending"
        assert body[3]["available_actions"] == ["block", "delete"]

    async def test_list_users_empty(self, client, mock_db, mock_redis, auth_headers):
        """Admin token + no users except admin -> 200 with single-item list."""
        _setup_redis_hit(mock_redis)

        admin = _make_fake_admin()
        mock_db.execute.side_effect = [
            _make_db_result(admin),
            _make_db_scalars_result([admin]),
        ]

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 1

    async def test_list_users_missing_auth_header(self, client):
        """Missing Authorization header -> 422 (FastAPI required header validation)."""
        response = await client.get(GET_URL)
        assert response.status_code == 422

    async def test_list_users_invalid_token(self, client, mock_db, mock_redis, auth_headers):
        """Token not found in Redis or DB -> 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value = _make_db_result(None)

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 401
        body = response.json()
        assert body["message"] == "Invalid or expired token"

    async def test_list_users_non_admin_user(self, client, mock_db, mock_redis, fake_account, auth_headers):
        """Valid token but user_type=1 (student) -> 403."""
        _setup_redis_hit(mock_redis)

        # fake_account has user_type=1 (student)
        mock_db.execute.side_effect = [
            _make_db_result(fake_account),
        ]

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 403
        body = response.json()
        assert body["message"] == "Admin permission required"

    async def test_list_users_account_not_found(self, client, mock_db, mock_redis, auth_headers):
        """Valid token but account deleted from DB -> 403."""
        _setup_redis_hit(mock_redis)

        mock_db.execute.side_effect = [
            _make_db_result(None),  # Account not found
        ]

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 403
        body = response.json()
        assert body["message"] == "Admin permission required"

    async def test_list_users_response_fields(self, client, mock_db, mock_redis, auth_headers):
        """Verify all required fields are present in each user object."""
        _setup_redis_hit(mock_redis)

        admin = _make_fake_admin()
        mock_db.execute.side_effect = [
            _make_db_result(admin),
            _make_db_scalars_result([admin]),
        ]

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        user = body[0]
        required_fields = {"id", "name", "email", "type", "status", "created_at", "available_actions"}
        assert required_fields == set(user.keys())
