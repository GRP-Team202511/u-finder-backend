"""
Router tests for POST /auth/settings/logout-all
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException, status
from tests.routers.utils.response_asserts import assert_message_response


URL = "/auth/settings/logout-all"
VALID_TOKEN = "valid-refresh-token-value"
BEARER = f"Bearer {VALID_TOKEN}"


def _make_user(*, user_id: int = 1):
    """Return a minimal mock Account object."""
    user = MagicMock()
    user.user_id = user_id
    return user


def _make_delete_result(rowcount: int):
    """Return a mock result whose .rowcount equals the given value."""
    result = MagicMock()
    result.rowcount = rowcount
    return result


def _make_select_result(value):
    """Return a mock result whose .scalar_one_or_none() returns value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class TestLogoutAllDevices:

    @patch("src.routers.auth.delete_all_user_sessions", new_callable=AsyncMock, return_value=3)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_logout_all_success(self, mock_auth, mock_del_sessions, client, mock_db):
        """Valid token + existing user -> 200 with revoked_count."""
        user = _make_user()
        mock_db.execute.side_effect = [
            _make_select_result(user),      # Account lookup
            _make_delete_result(3),         # DELETE refresh_token
        ]

        response = await client.post(URL, headers={"Authorization": BEARER})

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "All devices have been logged out"
        assert body["revoked_count"] == 3

    @patch("src.routers.auth.delete_all_user_sessions", new_callable=AsyncMock, return_value=0)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_logout_all_no_other_sessions(self, mock_auth, mock_del_sessions, client, mock_db):
        """User with only the current session -> 200 with revoked_count reflecting DB rows."""
        user = _make_user()
        mock_db.execute.side_effect = [
            _make_select_result(user),
            _make_delete_result(1),
        ]

        response = await client.post(URL, headers={"Authorization": BEARER})

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "All devices have been logged out"
        assert body["revoked_count"] == 1

    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_logout_all_user_not_found(self, mock_auth, client, mock_db):
        """Valid token but Account row missing -> 404."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.post(URL, headers={"Authorization": BEARER})

        assert response.status_code == 404
        assert_message_response(response.json(), "User not found")

    @patch(
        "src.routers.auth.get_current_user_id",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        ),
    )
    async def test_logout_all_invalid_token(self, mock_auth, client):
        """Invalid or expired token -> 401."""
        response = await client.post(URL, headers={"Authorization": BEARER})

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_logout_all_missing_auth_header(self, client):
        """Missing Authorization header -> 422."""
        response = await client.post(URL)

        assert response.status_code == 422
