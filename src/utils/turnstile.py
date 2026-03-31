# This code was completed by GRP Team 2025.11.
"""
Cloudflare Turnstile verification utility.
Validates Turnstile tokens via the siteverify API.
"""
import httpx
from fastapi import HTTPException, status

from src.config.logger import get_logger
from src.config.settings import get_settings

logger = get_logger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile_token(token: str, remote_ip: str | None = None) -> bool:
    """
    Verify a Cloudflare Turnstile token by calling the siteverify API.

    Args:
        token:     The turnstile response token from the frontend widget.
        remote_ip: Optional client IP for additional validation.

    Returns:
        True on success.

    Raises:
        HTTPException 400 if the token is missing or verification fails.
        HTTPException 500 if the server Turnstile configuration is invalid.
        HTTPException 503 if the Turnstile API is unreachable.
    """
    settings = get_settings()

    if not settings.turnstile_enabled:
        return True

    if not settings.turnstile_secret_key:
        logger.error(
            "TURNSTILE_ENABLED is true but TURNSTILE_SECRET_KEY is empty. "
            "Set the secret key or disable Turnstile."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Server misconfiguration: Turnstile secret key not set"},
        )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Missing turnstile_token"},
        )

    payload = {
        "secret": settings.turnstile_secret_key,
        "response": token,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(TURNSTILE_VERIFY_URL, data=payload)
            resp.raise_for_status()
            result = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Turnstile API returned HTTP %s: %s", exc.response.status_code, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Human verification service unavailable"},
        )
    except httpx.HTTPError as exc:
        logger.error("Turnstile API request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Human verification service unavailable"},
        )
    except (ValueError, KeyError) as exc:
        logger.error("Turnstile API returned non-JSON response: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Human verification service unavailable"},
        )

    if not result.get("success"):
        error_codes = result.get("error-codes", [])
        logger.warning("Turnstile verification failed: %s", error_codes)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Human verification failed"},
        )

    return True
