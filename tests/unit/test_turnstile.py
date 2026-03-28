"""
Unit tests for Cloudflare Turnstile verification utility.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException

from src.utils.turnstile import verify_turnstile_token


# ── Helper: build a mock Settings object ──
def _settings(enabled: bool = True, secret: str = "test-secret"):
    s = MagicMock()
    s.turnstile_enabled = enabled
    s.turnstile_secret_key = secret
    return s


# ── Disabled ──
@pytest.mark.asyncio
async def test_turnstile_disabled_skips_verification():
    """When turnstile_enabled=False, any token (even empty) should pass."""
    with patch("src.utils.turnstile.get_settings", return_value=_settings(enabled=False)):
        result = await verify_turnstile_token("", None)
        assert result is True


@pytest.mark.asyncio
async def test_turnstile_disabled_with_no_token():
    with patch("src.utils.turnstile.get_settings", return_value=_settings(enabled=False)):
        result = await verify_turnstile_token("", "1.2.3.4")
        assert result is True


# ── Enabled: missing token ──
@pytest.mark.asyncio
async def test_turnstile_enabled_missing_token_raises_400():
    with patch("src.utils.turnstile.get_settings", return_value=_settings(enabled=True)):
        with pytest.raises(HTTPException) as exc_info:
            await verify_turnstile_token("", "1.2.3.4")
        assert exc_info.value.status_code == 400
        assert "Missing" in exc_info.value.detail["message"]


# ── Enabled: successful verification ──
@pytest.mark.asyncio
async def test_turnstile_success():
    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.utils.turnstile.get_settings", return_value=_settings(enabled=True)),
        patch("src.utils.turnstile.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await verify_turnstile_token("valid-token", "1.2.3.4")
        assert result is True

        # Verify the right payload was sent
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["data"]["secret"] == "test-secret"
        assert call_kwargs[1]["data"]["response"] == "valid-token"
        assert call_kwargs[1]["data"]["remoteip"] == "1.2.3.4"


# ── Enabled: failed verification ──
@pytest.mark.asyncio
async def test_turnstile_failure_raises_400():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "success": False,
        "error-codes": ["invalid-input-response"],
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.utils.turnstile.get_settings", return_value=_settings(enabled=True)),
        patch("src.utils.turnstile.httpx.AsyncClient", return_value=mock_client),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_turnstile_token("bad-token", "1.2.3.4")
        assert exc_info.value.status_code == 400
        assert "failed" in exc_info.value.detail["message"]


# ── Enabled: API unreachable ──
@pytest.mark.asyncio
async def test_turnstile_api_error_raises_503():
    import httpx as _httpx

    mock_client = AsyncMock()
    mock_client.post.side_effect = _httpx.ConnectError("Connection refused")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.utils.turnstile.get_settings", return_value=_settings(enabled=True)),
        patch("src.utils.turnstile.httpx.AsyncClient", return_value=mock_client),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_turnstile_token("some-token", "1.2.3.4")
        assert exc_info.value.status_code == 503
        assert "unavailable" in exc_info.value.detail["message"]


# ── Enabled: no remote_ip (optional field) ──
@pytest.mark.asyncio
async def test_turnstile_success_without_ip():
    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.utils.turnstile.get_settings", return_value=_settings(enabled=True)),
        patch("src.utils.turnstile.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await verify_turnstile_token("valid-token", None)
        assert result is True

        # Verify remoteip is NOT in payload when None
        call_kwargs = mock_client.post.call_args
        assert "remoteip" not in call_kwargs[1]["data"]
