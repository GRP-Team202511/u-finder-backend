# This code was completed by GRP Team 2025.11.
"""
Router tests for PUT /auth/settings/username
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException, status
from tests.routers.utils.response_asserts import assert_message_response


URL = "/auth/settings/username"
VALID_TOKEN = "valid-refresh-token-value"
BEARER = f"Bearer {VALID_TOKEN}"


def _make_user(*, user_id: int = 1, email: str = "test@example.com",
               user_name: str = "Test User", user_type: int = 1):
    """Return a minimal mock Account object."""
    user = MagicMock()
    user.user_id = user_id
    user.email = email
    user.user_name = user_name
    user.user_type = user_type
    return user


class TestUpdateUsername:
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_update_username_success(self, mock_auth, client, mock_db):
        """Authenticated user should update username successfully."""
        user = _make_user(user_name="OldName")
        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        response = await client.put(
            URL,
            json={"username": "NewName"},
            headers={"Authorization": BEARER},
        )

        assert response.status_code == 200
        body = response.json()
        assert body == {"message": "Username updated successfully"}
        assert user.user_name == "NewName"

    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_update_username_user_not_found(self, mock_auth, client, mock_db):
        """Should return 404 when user_id has no matching Account row."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.put(
            URL,
            json={"username": "NewName"},
            headers={"Authorization": BEARER},
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "User not found")

    async def test_update_username_missing_auth_header(self, client):
        """Missing Authorization header must return 422."""
        response = await client.put(URL, json={"username": "NewName"})

        assert response.status_code == 422

    @patch(
        "src.routers.auth.get_current_user_id",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        ),
    )
    async def test_update_username_invalid_token(self, mock_auth, client):
        """An invalid or expired token must return 401."""
        response = await client.put(
            URL,
            json={"username": "NewName"},
            headers={"Authorization": BEARER},
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_update_username_empty_string_validation_error(self, client):
        """Empty username must return 422 validation error."""
        response = await client.put(
            URL,
            json={"username": ""},
            headers={"Authorization": BEARER},
        )

        assert response.status_code == 422

    async def test_update_username_too_long_validation_error(self, client):
        """Username longer than 20 chars must return 422 validation error."""
        response = await client.put(
            URL,
            json={"username": "a" * 21},
            headers={"Authorization": BEARER},
        )

        assert response.status_code == 422
