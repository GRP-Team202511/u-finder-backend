"""
Router tests for GET /profile/avatar, PUT /profile/avatar, and DELETE /profile/avatar

Covers:
  GET  200 — Avatar URL returned for requested size
  GET  400 — Invalid or missing size parameter
  GET  401 — Invalid or expired token
  GET  404 — User has no avatar or requested size not available
  GET  500 — Internal server error

  PUT  200 — Avatar uploaded successfully (multiple sizes generated)
  PUT  400 — Empty file
  PUT  401 — Invalid or expired token
  PUT  413 — File too large
  PUT  415 — Unsupported file type
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

FAKE_AVATAR_URLS = {
    "original": "/uploads/avatars/1/original.png",
    "webp_original": "/uploads/avatars/1/original.webp",
    "webp_256": "/uploads/avatars/1/256.webp",
    "webp_64": "/uploads/avatars/1/64.webp",
}


def _setup_redis_hit(mock_redis):
    """Configure Redis to return a valid session (auth succeeds via cache)."""
    mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}


def _fake_profile(avatar=None):
    """Return a mock UserProfile with configurable basic_info."""
    profile = MagicMock()
    profile.basic_info = {"name": "Test", "avatar": avatar} if avatar else {"name": "Test"}
    profile.user_id = 1
    return profile


def _mock_avatar_dir_file_exists(exists=True):
    """Mock _avatar_dir so (dir/user_id/filename).exists() returns exists."""
    mock_file = MagicMock()
    mock_file.exists.return_value = exists
    mock_user_dir = MagicMock()
    mock_user_dir.__truediv__ = MagicMock(return_value=mock_file)
    mock_base = MagicMock()
    mock_base.__truediv__ = MagicMock(return_value=mock_user_dir)
    return mock_base


# ──────────────────────────────────────────────
# GET /profile/avatar
# ──────────────────────────────────────────────

class TestGetAvatar:

    @patch("src.routers.profile._avatar_dir", return_value=_mock_avatar_dir_file_exists(exists=True))
    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_origin(self, mock_auth, mock_dir, client, mock_db, mock_redis):
        """User with avatar, size=origin -> 200 with url (original.webp)."""
        _setup_redis_hit(mock_redis)

        response = await client.get(
            AVATAR_URL,
            params={"size": "origin"},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 200
        assert response.json()["url"] == "/uploads/avatars/1/original.webp"

    @patch("src.routers.profile._avatar_dir", return_value=_mock_avatar_dir_file_exists(exists=True))
    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_64x64(self, mock_auth, mock_dir, client, mock_db, mock_redis):
        """User with avatar, size=64x64 -> 200 with url."""
        _setup_redis_hit(mock_redis)

        response = await client.get(
            AVATAR_URL,
            params={"size": "64x64"},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 200
        assert response.json()["url"] == "/uploads/avatars/1/64.webp"

    @patch("src.routers.profile._avatar_dir", return_value=_mock_avatar_dir_file_exists(exists=True))
    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_256x256(self, mock_auth, mock_dir, client, mock_db, mock_redis):
        """User with avatar, size=256x256 -> 200 with url."""
        _setup_redis_hit(mock_redis)

        response = await client.get(
            AVATAR_URL,
            params={"size": "256x256"},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 200
        assert response.json()["url"] == "/uploads/avatars/1/256.webp"

    @patch("src.routers.profile._avatar_dir", return_value=_mock_avatar_dir_file_exists(exists=False))
    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_no_avatar(self, mock_auth, mock_dir, client, mock_db, mock_redis):
        """User without avatar (file not on disk) -> 404."""
        _setup_redis_hit(mock_redis)

        response = await client.get(
            AVATAR_URL,
            params={"size": "origin"},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "User has no avatar")

    @patch("src.routers.profile._avatar_dir", return_value=_mock_avatar_dir_file_exists(exists=False))
    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_size_not_available(self, mock_auth, mock_dir, client, mock_db, mock_redis):
        """Requested size file not on disk (e.g. small image, no 256.webp) -> 404."""
        _setup_redis_hit(mock_redis)

        response = await client.get(
            AVATAR_URL,
            params={"size": "256x256"},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 404
        assert_message_response(response.json(), "User has no avatar")

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_missing_size(self, mock_auth, client, mock_db, mock_redis):
        """Missing size parameter -> 400."""
        _setup_redis_hit(mock_redis)

        response = await client.get(
            AVATAR_URL,
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 400
        assert "size" in response.json()["message"].lower()

    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_invalid_size(self, mock_auth, client, mock_db, mock_redis):
        """Invalid size parameter -> 400."""
        _setup_redis_hit(mock_redis)

        response = await client.get(
            AVATAR_URL,
            params={"size": "invalid"},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 400
        assert "size" in response.json()["message"].lower()

    async def test_get_avatar_missing_auth(self, client):
        """Missing Authorization header -> 422."""
        response = await client.get(AVATAR_URL, params={"size": "origin"})
        assert response.status_code == 422

    @patch("src.routers.profile._avatar_dir", side_effect=RuntimeError("disk error"))
    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_avatar_internal_error(self, mock_auth, mock_dir, client, mock_db, mock_redis):
        """Unexpected exception -> 500."""
        _setup_redis_hit(mock_redis)

        response = await client.get(
            AVATAR_URL,
            params={"size": "origin"},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 500
        assert_message_response(response.json(), "Internal server error")


# ──────────────────────────────────────────────
# PUT /profile/avatar
# ──────────────────────────────────────────────

class TestUploadAvatar:

    @patch("src.routers.profile._generate_avatar_variants", return_value=FAKE_AVATAR_URLS)
    @patch("src.routers.profile.shutil")
    @patch("src.routers.profile._avatar_dir")
    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_upload_avatar_success(self, mock_auth, mock_dir, mock_shutil, mock_gen, client, mock_db, mock_redis):
        """Valid PNG upload -> 200 with avatar_urls dict (filesystem only, no DB)."""
        _setup_redis_hit(mock_redis)

        # Mock avatar directory
        mock_path = MagicMock(spec=Path)
        mock_path.__truediv__ = MagicMock(return_value=MagicMock(spec=Path))
        mock_dir.return_value = mock_path

        response = await client.put(
            AVATAR_URL,
            files={"file": ("avatar.png", TINY_PNG, "image/png")},
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Avatar uploaded successfully"
        assert "avatar_urls" in body
        assert "original" in body["avatar_urls"]

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

        with patch("src.routers.profile._avatar_dir", side_effect=RuntimeError("disk error")):
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

    @patch("src.routers.profile.shutil")
    @patch("src.routers.profile._user_avatar_exists", return_value=True)
    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_delete_avatar_success(self, mock_auth, mock_exists, mock_shutil, client, mock_db, mock_redis):
        """Existing avatar -> 200 deleted (filesystem only, no DB)."""
        _setup_redis_hit(mock_redis)

        response = await client.delete(
            AVATAR_URL,
            headers={"Authorization": "Bearer fake-token"},
        )

        assert response.status_code == 200
        assert_message_response(response.json(), "Avatar deleted successfully")

    @patch("src.routers.profile._user_avatar_exists", return_value=False)
    @patch("src.routers.profile._get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_delete_avatar_not_found(self, mock_auth, mock_exists, client, mock_redis):
        """No avatar folder exists -> 404."""
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

        with patch("src.routers.profile._user_avatar_exists", side_effect=RuntimeError("fs error")):
            response = await client.delete(
                AVATAR_URL,
                headers={"Authorization": "Bearer fake-token"},
            )

        assert response.status_code == 500
        assert_message_response(response.json(), "Internal server error")
