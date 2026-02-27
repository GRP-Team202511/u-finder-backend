"""
Router tests for POST /auth/logout
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from tests.routers.utils.response_asserts import (
    assert_detail_message_response,
    assert_message_response,
    assert_validation_error,
)


LOGOUT_URL = "/auth/logout"
VALID_TOKEN = "valid-refresh-token-value"
BEARER = f"Bearer {VALID_TOKEN}"


def _make_refresh_token_record(user_id: int = 1):
    """Return a minimal mock RefreshToken ORM object."""
    rt = MagicMock()
    rt.id = 1
    rt.user_id = user_id
    rt.token_hashed = "hashed-value"
    return rt


class TestLogout:
    @patch("src.routers.auth.delete_session", new_callable=AsyncMock)
    @patch("src.routers.auth.get_session", new_callable=AsyncMock, return_value=None)
    async def test_logout_success_cache_miss(
        self, mock_get_session, mock_delete_session, client, mock_db
    ):
        """Token found via DB fallback (cache miss) must return 200."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = (
            _make_refresh_token_record()
        )

        response = await client.post(
            LOGOUT_URL, headers={"Authorization": BEARER}
        )

        assert response.status_code == 200
        assert_message_response(response.json(), "Logged out successfully")

    @patch("src.routers.auth.delete_session", new_callable=AsyncMock)
    @patch("src.routers.auth.get_session", new_callable=AsyncMock, return_value={"user_id": "1"})
    async def test_logout_success_cache_hit(
        self, mock_get_session, mock_delete_session, client, mock_db
    ):
        """Token found via Redis cache must also return 200."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = (
            _make_refresh_token_record()
        )

        response = await client.post(
            LOGOUT_URL, headers={"Authorization": BEARER}
        )

        assert response.status_code == 200
        assert_message_response(response.json(), "Logged out successfully")

    @patch("src.routers.auth.delete_session", new_callable=AsyncMock)
    @patch("src.routers.auth.get_session", new_callable=AsyncMock, return_value=None)
    async def test_logout_invalid_token(
        self, mock_get_session, mock_delete_session, client, mock_db
    ):
        """A token that does not exist in DB or cache must return 401."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.post(
            LOGOUT_URL, headers={"Authorization": BEARER}
        )

        assert response.status_code == 401
        assert_detail_message_response(response.json(), "Invalid or expired token")

    async def test_logout_invalid_header_format(self, client):
        """Authorization header without 'Bearer ' prefix must return 401."""
        response = await client.post(
            LOGOUT_URL, headers={"Authorization": VALID_TOKEN}
        )

        assert response.status_code == 401
        assert_detail_message_response(response.json(), "Invalid authorization header format")

    async def test_logout_missing_authorization_header(self, client):
        """Missing Authorization header must return 422 (required header)."""
        response = await client.post(LOGOUT_URL)
        assert response.status_code == 422
        assert_validation_error(response.json())
