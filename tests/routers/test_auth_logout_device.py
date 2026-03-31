# This code was completed by GRP Team 2025.11.
"""
Router tests for DELETE /auth/settings/devices/{session_id}
"""
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException, status
from tests.routers.utils.response_asserts import assert_message_response

URL = "/auth/settings/devices"
VALID_TOKEN = "valid-refresh-token-value"
BEARER = f"Bearer {VALID_TOKEN}"
FAKE_CURRENT_HASH = "current-token-hash"


def _make_refresh_token(
    *,
    id: int = 42,
    user_id: int = 1,
    token_hashed: str = "other-session-hash",
):
    """Return a minimal mock RefreshToken ORM object."""
    rt = MagicMock()
    rt.id = id
    rt.user_id = user_id
    rt.token_hashed = token_hashed
    return rt


def _make_scalar_result(value):
    """Return a mock result whose .scalar_one_or_none() returns value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_delete_result(rowcount: int = 1):
    result = MagicMock()
    result.rowcount = rowcount
    return result


class TestLogoutDevice:

    @patch("src.routers.auth.delete_session_by_hash", new_callable=AsyncMock)
    @patch("src.routers.auth.hash_token", return_value=FAKE_CURRENT_HASH)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_logout_device_success(
        self, mock_auth, mock_hash, mock_del_session, client, mock_db
    ):
        """Valid token + existing non-current session -> 200."""
        session = _make_refresh_token(id=42, token_hashed="other-session-hash")
        mock_db.execute.side_effect = [
            _make_scalar_result(session),      # SELECT RefreshToken
            _make_delete_result(1),            # DELETE RefreshToken
        ]

        response = await client.delete(
            f"{URL}/42", headers={"Authorization": BEARER}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Device session has been logged out"
        mock_del_session.assert_awaited_once()
        args = mock_del_session.call_args[0]
        assert args[1] == "other-session-hash"
        assert args[2] == 1

    @patch("src.routers.auth.delete_session_by_hash", new_callable=AsyncMock)
    @patch("src.routers.auth.hash_token", return_value=FAKE_CURRENT_HASH)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_logout_device_success_verify_redis_cleanup(
        self, mock_auth, mock_hash, mock_del_session, client, mock_db
    ):
        """Successful logout should clean up both DB and Redis."""
        session = _make_refresh_token(id=10, token_hashed="digest-xyz")
        mock_db.execute.side_effect = [
            _make_scalar_result(session),
            _make_delete_result(1),
        ]

        response = await client.delete(
            f"{URL}/10", headers={"Authorization": BEARER}
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Device session has been logged out"
        args = mock_del_session.call_args[0]
        assert args[1] == "digest-xyz"
        assert args[2] == 1

    @patch("src.routers.auth.hash_token", return_value=FAKE_CURRENT_HASH)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_logout_device_is_current_returns_400(
        self, mock_auth, mock_hash, client, mock_db
    ):
        """Attempting to logout the current device -> 400."""
        session = _make_refresh_token(id=42, token_hashed=FAKE_CURRENT_HASH)
        mock_db.execute.return_value = _make_scalar_result(session)

        response = await client.delete(
            f"{URL}/42", headers={"Authorization": BEARER}
        )

        assert response.status_code == 400
        assert_message_response(
            response.json(),
            "Cannot logout current device, use /auth/logout instead",
        )

    @patch("src.routers.auth.hash_token", return_value=FAKE_CURRENT_HASH)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_logout_device_session_not_found(
        self, mock_auth, mock_hash, client, mock_db
    ):
        """Session ID does not exist -> 404."""
        mock_db.execute.return_value = _make_scalar_result(None)

        response = await client.delete(
            f"{URL}/999", headers={"Authorization": BEARER}
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "Session not found")

    @patch("src.routers.auth.hash_token", return_value=FAKE_CURRENT_HASH)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_logout_device_belongs_to_other_user(
        self, mock_auth, mock_hash, client, mock_db
    ):
        """Session belongs to another user -> 404 (query filters by user_id)."""
        mock_db.execute.return_value = _make_scalar_result(None)

        response = await client.delete(
            f"{URL}/42", headers={"Authorization": BEARER}
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "Session not found")

    @patch(
        "src.routers.auth.get_current_user_id",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        ),
    )
    async def test_logout_device_invalid_token(self, mock_auth, client):
        """Invalid or expired token -> 401."""
        response = await client.delete(
            f"{URL}/42", headers={"Authorization": BEARER}
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_logout_device_missing_auth_header(self, client):
        """Missing Authorization header -> 422."""
        response = await client.delete(f"{URL}/42")

        assert response.status_code == 422

    @patch("src.routers.auth.hash_token", return_value=FAKE_CURRENT_HASH)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_logout_device_db_error(self, mock_auth, mock_hash, client, mock_db):
        """DB query raises unexpected exception -> 500."""
        mock_db.execute.side_effect = RuntimeError("DB connection lost")

        response = await client.delete(
            f"{URL}/42", headers={"Authorization": BEARER}
        )

        assert response.status_code == 500
        assert_message_response(response.json(), "Internal server error")

    @patch("src.routers.auth.delete_session_by_hash", new_callable=AsyncMock)
    @patch("src.routers.auth.hash_token", return_value=FAKE_CURRENT_HASH)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_logout_device_redis_none(
        self, mock_auth, mock_hash, mock_del_session, client, mock_db, mock_redis
    ):
        """Redis unavailable (None) should still succeed with DB-only cleanup."""
        session = _make_refresh_token(id=42, token_hashed="other-hash")
        mock_db.execute.side_effect = [
            _make_scalar_result(session),
            _make_delete_result(1),
        ]

        # Override redis to None
        from tests.conftest import build_test_app
        from src.database.connection import get_db
        from src.database.redis_connection import get_redis

        app = build_test_app()

        async def override_get_db():
            yield mock_db

        async def override_get_redis():
            yield None

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_redis] = override_get_redis

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            response = await c.delete(
                f"{URL}/42", headers={"Authorization": BEARER}
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Device session has been logged out"
        mock_del_session.assert_not_awaited()
