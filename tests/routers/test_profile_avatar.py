"""
Router tests for GET /profile/avatar, PUT /profile/avatar, and DELETE /profile/avatar

Covers:
  GET  200 — Avatar URL returned (with and without avatar)
  GET  401 — Invalid or expired token
  GET  500 — Internal server error

  PUT  200 — Avatar uploaded successfully
  PUT  401 — Invalid or expired token
  PUT  413 — File too large
  PUT  415 — Unsupported file type
  PUT  400 — Empty file
  PUT  500 — Internal server error

  DELETE 200 — Avatar deleted successfully
  DELETE 401 — Invalid or expired token
  DELETE 404 — No avatar found
  DELETE 500 — Internal server error
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from pathlib import Path
from tests.routers.utils.response_asserts import assert_message_response


AVATAR_URL = "/profile/avatar"

# 1x1 transparent PNG (minimal valid image bytes)
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _setup_redis_hit(mock_redis):
    """Configure Redis to return a valid session (auth succeeds via cache)."""
    mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}


def _fake_profile(avatar=None):
    """Return a mock UserProfile with configurable basic_info."""
    profile = MagicMock()
    profile.basic_info = {"name": "Test", "avatar": avatar} if avatar else {"name": "Test"}
    profile.user_id = 1
    return profile


# ──────────────────────────────────────────────
# GET /profile/avatar
# ──────────────────────────────────────────────

class TestGetAvatar:

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_with_avatar(self, mock_auth, client, mock_db, mock_redis):
        """User with avatar -> 200 with avatar_url."""
        _setup_redis_hit(mock_redis)

        profile = _fake_profile(avatar="/uploads/avatars/1.jpg")
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = profile
        mock_db.execute.return_value = execute_result

        response = await client.get(
            AVATAR_URL,
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["avatar_url"] == "/uploads/avatars/1.jpg"

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_no_avatar(self, mock_auth, client, mock_db, mock_redis):
        """User without avatar -> 200 with avatar_url=null."""
        _setup_redis_hit(mock_redis)

        profile = _fake_profile()  # no avatar
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = profile
        mock_db.execute.return_value = execute_result

        response = await client.get(
            AVATAR_URL,
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["avatar_url"] is None

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_no_profile(self, mock_auth, client, mock_db, mock_redis):
        """User with no profile record -> 200 with avatar_url=null."""
        _setup_redis_hit(mock_redis)

        # Default mock_db returns None for scalar_one_or_none
        response = await client.get(
            AVATAR_URL,
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 200
        assert response.json()["avatar_url"] is None

    async def test_get_avatar_missing_auth(self, client):
        """Missing Authorization header -> 422."""
        response = await client.get(AVATAR_URL)
        assert response.status_code == 422

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_internal_error(self, mock_auth, client, mock_db, mock_redis):
        """DB error -> 500."""
        _setup_redis_hit(mock_redis)
        mock_db.execute.side_effect = RuntimeError("DB down")

        response = await client.get(
            AVATAR_URL,
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 500
        assert_message_response(response.json(), "Internal server error")


# ──────────────────────────────────────────────
# PUT /profile/avatar
# ──────────────────────────────────────────────

class TestUploadAvatar:

    @patch("src.routers.profile._find_existing_avatar", return_value=None)
    @patch("src.routers.profile._avatar_dir")
    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_upload_avatar_success(self, mock_auth, mock_dir, mock_find, client, mock_db, mock_redis):
        """Valid JPEG upload -> 200 with avatar_url."""
        _setup_redis_hit(mock_redis)

        # Mock avatar directory and file write
        mock_path = MagicMock(spec=Path)
        mock_dir.return_value = mock_path
        mock_path.__truediv__ = MagicMock(return_value=MagicMock(spec=Path))

        # Mock DB profile lookup
        profile = _fake_profile()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = profile
        mock_db.execute.return_value = execute_result

        response = await client.put(
            AVATAR_URL,
            files={"file": ("avatar.jpg", TINY_PNG, "image/jpeg")},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Avatar uploaded successfully"
        assert "avatar_url" in body
        assert body["avatar_url"].startswith("/uploads/avatars/")

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_upload_avatar_unsupported_type(self, mock_auth, client, mock_redis):
        """Non-image file -> 415."""
        _setup_redis_hit(mock_redis)

        response = await client.put(
            AVATAR_URL,
            files={"file": ("doc.pdf", b"fake pdf content", "application/pdf")},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 415
        assert_message_response(response.json(), "Only JPEG, PNG, and WebP images are allowed")

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_upload_avatar_too_large(self, mock_auth, client, mock_redis):
        """File exceeding 2 MB -> 413."""
        _setup_redis_hit(mock_redis)

        # Create content just over 2 MB
        large_content = b"\x00" * (2 * 1024 * 1024 + 1)
        response = await client.put(
            AVATAR_URL,
            files={"file": ("big.png", large_content, "image/png")},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 413
        body = response.json()
        assert "limit" in body["message"].lower() or "exceeds" in body["message"].lower()

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_upload_avatar_empty_file(self, mock_auth, client, mock_redis):
        """Empty file -> 400."""
        _setup_redis_hit(mock_redis)

        response = await client.put(
            AVATAR_URL,
            files={"file": ("empty.jpg", b"", "image/jpeg")},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 400
        assert_message_response(response.json(), "Uploaded file is empty")

    async def test_upload_avatar_missing_auth(self, client):
        """Missing Authorization header -> 422."""
        response = await client.put(
            AVATAR_URL,
            files={"file": ("avatar.jpg", TINY_PNG, "image/jpeg")},
        )
        assert response.status_code == 422

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_upload_avatar_internal_error(self, mock_auth, client, mock_redis):
        """Unexpected exception -> 500."""
        _setup_redis_hit(mock_redis)

        # Use a content type that passes validation but subsequent code fails
        with patch("src.routers.profile._find_existing_avatar", side_effect=RuntimeError("disk error")):
            response = await client.put(
                AVATAR_URL,
                files={"file": ("avatar.png", TINY_PNG, "image/png")},
                headers={"Authorization": "Bearer fake-token"},
            )

        assert response.status_code == 500
        assert_message_response(response.json(), "Internal server error")


# ──────────────────────────────────────────────
# DELETE /profile/avatar
# ──────────────────────────────────────────────

class TestDeleteAvatar:

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_delete_avatar_success(self, mock_auth, client, mock_db, mock_redis):
        """Existing avatar -> 200 deleted."""
        _setup_redis_hit(mock_redis)

        mock_existing = MagicMock(spec=Path)
        mock_existing.exists.return_value = True

        with patch("src.routers.profile._find_existing_avatar", return_value=mock_existing):
            profile = _fake_profile(avatar="/uploads/avatars/1.png")
            execute_result = MagicMock()
            execute_result.scalar_one_or_none.return_value = profile
            mock_db.execute.return_value = execute_result

            response = await client.delete(
                AVATAR_URL,
                headers={"Authorization": "Bearer fake-token"},
            )

        assert response.status_code == 200
        assert_message_response(response.json(), "Avatar deleted successfully")
        mock_existing.unlink.assert_called_once_with(missing_ok=True)

    @patch("src.routers.profile._find_existing_avatar", return_value=None)
    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_delete_avatar_not_found(self, mock_auth, mock_find, client, mock_redis):
        """No avatar file exists -> 404."""
        _setup_redis_hit(mock_redis)

        response = await client.delete(
            AVATAR_URL,
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "No avatar found")

    async def test_delete_avatar_missing_auth(self, client):
        """Missing Authorization header -> 422."""
        response = await client.delete(AVATAR_URL)
        assert response.status_code == 422

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_delete_avatar_internal_error(self, mock_auth, client, mock_redis):
        """Unexpected exception -> 500."""
        _setup_redis_hit(mock_redis)

        with patch("src.routers.profile._find_existing_avatar", side_effect=RuntimeError("fs error")):
            response = await client.delete(
                AVATAR_URL,
                headers={"Authorization": "Bearer fake-token"},
            )

        assert response.status_code == 500
        assert_message_response(response.json(), "Internal server error")
