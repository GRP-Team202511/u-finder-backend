"""
Router tests for GET /auth/settings/devices
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException, status
from tests.routers.utils.response_asserts import assert_message_response


URL = "/auth/settings/devices"
VALID_TOKEN = "valid-refresh-token-value"
BEARER = f"Bearer {VALID_TOKEN}"
FAKE_TOKEN_HASH = "fakehash123"

CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
SAFARI_MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"


def _make_refresh_token(
    *,
    id: int = 1,
    user_id: int = 1,
    token_hashed: str = "other-hash",
    user_agent: str = CHROME_UA,
    created_at=None,
    expire_at=None,
):
    """Return a mock RefreshToken ORM object."""
    rt = MagicMock()
    rt.id = id
    rt.user_id = user_id
    rt.token_hashed = token_hashed
    rt.user_agent = user_agent
    rt.created_at = created_at or datetime.now(timezone.utc) - timedelta(days=1)
    rt.expire_at = expire_at or datetime.now(timezone.utc) + timedelta(days=29)
    return rt


def _make_scalars_result(rows):
    """Return a mock result whose .scalars().all() returns the given rows."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = rows
    result.scalars.return_value = scalars_mock
    return result


class TestGetDevices:

    @patch("src.routers.auth.hash_token", return_value=FAKE_TOKEN_HASH)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_devices_success(self, mock_auth, mock_hash, client, mock_db):
        """Valid token with two sessions -> 200 with device list."""
        sessions = [
            _make_refresh_token(id=42, token_hashed=FAKE_TOKEN_HASH, user_agent=CHROME_UA),
            _make_refresh_token(id=38, token_hashed="different-hash", user_agent=SAFARI_MOBILE_UA),
        ]
        mock_db.execute.return_value = _make_scalars_result(sessions)

        response = await client.get(URL, headers={"Authorization": BEARER})

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert len(body["devices"]) == 2

        # First device should be flagged as current
        current = body["devices"][0]
        assert current["session_id"] == 42
        assert current["is_current"] is True
        assert current["browser"] == "Chrome 122"
        assert current["os"] == "Windows 10"
        assert current["device_type"] == "PC"

        # Second device should not be current
        other = body["devices"][1]
        assert other["session_id"] == 38
        assert other["is_current"] is False
        assert other["device_type"] == "Mobile"

    @patch("src.routers.auth.hash_token", return_value=FAKE_TOKEN_HASH)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_devices_empty(self, mock_auth, mock_hash, client, mock_db):
        """Valid token but no active sessions -> 200 with empty list."""
        mock_db.execute.return_value = _make_scalars_result([])

        response = await client.get(URL, headers={"Authorization": BEARER})

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["devices"] == []

    @patch("src.routers.auth.hash_token", return_value=FAKE_TOKEN_HASH)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_devices_unknown_user_agent(self, mock_auth, mock_hash, client, mock_db):
        """Session with empty user_agent -> graceful degradation to 'Unknown'."""
        sessions = [
            _make_refresh_token(id=10, token_hashed=FAKE_TOKEN_HASH, user_agent=""),
        ]
        mock_db.execute.return_value = _make_scalars_result(sessions)

        response = await client.get(URL, headers={"Authorization": BEARER})

        assert response.status_code == 200
        device = response.json()["devices"][0]
        assert device["browser"] == "Unknown"
        assert device["os"] == "Unknown"
        assert device["device_type"] == "Unknown"
        assert device["is_current"] is True

    @patch(
        "src.routers.auth.get_current_user_id",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        ),
    )
    async def test_get_devices_invalid_token(self, mock_auth, client):
        """Invalid or expired token -> 401."""
        response = await client.get(URL, headers={"Authorization": BEARER})

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_get_devices_missing_auth_header(self, client):
        """Missing Authorization header -> 422."""
        response = await client.get(URL)

        assert response.status_code == 422

    @patch("src.routers.auth.hash_token", return_value=FAKE_TOKEN_HASH)
    @patch("src.routers.auth.get_current_user_id", new_callable=AsyncMock, return_value=1)
    async def test_get_devices_internal_error(self, mock_auth, mock_hash, client, mock_db):
        """DB query raises unexpected exception -> 500."""
        mock_db.execute.side_effect = RuntimeError("DB connection lost")

        response = await client.get(URL, headers={"Authorization": BEARER})

        assert response.status_code == 500
        assert_message_response(response.json(), "Internal server error")
