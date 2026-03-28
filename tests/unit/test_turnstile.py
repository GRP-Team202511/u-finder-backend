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


def _mock_http_client(response):
    """Build an AsyncMock httpx client that returns *response* on post()."""
    mock_client = AsyncMock()
    mock_client.post.return_value = response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _ok_response(payload: dict | None = None):
    """Build a mock httpx.Response with status 200 and JSON body."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()  # no-op
    resp.json.return_value = payload or {"success": True}
    return resp


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


# ── Enabled: missing secret key (#4) ──
@pytest.mark.asyncio
async def test_turnstile_enabled_empty_secret_raises_500():
    """Server misconfiguration: enabled but no secret key → 500."""
    with patch("src.utils.turnstile.get_settings", return_value=_settings(enabled=True, secret="")):
        with pytest.raises(HTTPException) as exc_info:
            await verify_turnstile_token("some-token", "1.2.3.4")
        assert exc_info.value.status_code == 500
        assert "misconfiguration" in exc_info.value.detail["message"]


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
    mock_client = _mock_http_client(_ok_response())

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
    resp = _ok_response({"success": False, "error-codes": ["invalid-input-response"]})
    mock_client = _mock_http_client(resp)

    with (
        patch("src.utils.turnstile.get_settings", return_value=_settings(enabled=True)),
        patch("src.utils.turnstile.httpx.AsyncClient", return_value=mock_client),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_turnstile_token("bad-token", "1.2.3.4")
        assert exc_info.value.status_code == 400
        assert "failed" in exc_info.value.detail["message"]


# ── Enabled: API unreachable (connection error) ──
@pytest.mark.asyncio
async def test_turnstile_api_connect_error_raises_503():
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


# ── Enabled: API returns non-2xx (#3) ──
@pytest.mark.asyncio
async def test_turnstile_api_5xx_raises_503():
    """Cloudflare returning 5xx should result in 503, not 500."""
    import httpx as _httpx

    resp = MagicMock()
    resp.status_code = 502
    resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
        "Bad Gateway", request=MagicMock(), response=resp
    )

    mock_client = _mock_http_client(resp)

    with (
        patch("src.utils.turnstile.get_settings", return_value=_settings(enabled=True)),
        patch("src.utils.turnstile.httpx.AsyncClient", return_value=mock_client),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await verify_turnstile_token("some-token", "1.2.3.4")
        assert exc_info.value.status_code == 503
        assert "unavailable" in exc_info.value.detail["message"]


# ── Enabled: API returns non-JSON body (#3) ──
@pytest.mark.asyncio
async def test_turnstile_api_non_json_raises_503():
    """HTML error page from Cloudflare should result in 503."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.side_effect = ValueError("No JSON object could be decoded")

    mock_client = _mock_http_client(resp)

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
    mock_client = _mock_http_client(_ok_response())

    with (
        patch("src.utils.turnstile.get_settings", return_value=_settings(enabled=True)),
        patch("src.utils.turnstile.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await verify_turnstile_token("valid-token", None)
        assert result is True

        # Verify remoteip is NOT in payload when None
        call_kwargs = mock_client.post.call_args
        assert "remoteip" not in call_kwargs[1]["data"]
