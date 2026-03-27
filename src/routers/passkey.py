"""
Passkey (WebAuthn/FIDO2) router module
Provides registration and passwordless login via FIDO2-compliant authenticators.
Each user can register multiple passkeys for different devices.
"""
import json
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
)
from webauthn.helpers.structs import (
    PublicKeyCredentialDescriptor,
    UserVerificationRequirement,
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    AttestationConveyancePreference,
)
from webauthn.helpers import (
    options_to_json,
    bytes_to_base64url,
    base64url_to_bytes,
)

from src.config.logger import get_logger
from src.config.settings import get_settings
from src.database import get_db, get_redis, Account, Passkey, RefreshToken
from src.schemas.passkey import (
    PasskeyRegisterOptionsResponse,
    PasskeyRegisterVerifyRequest,
    PasskeyRegisterVerifyResponse,
    PasskeyLoginOptionsRequest,
    PasskeyLoginOptionsResponse,
    PasskeyLoginVerifyRequest,
    PasskeyLoginVerifyResponse,
    PasskeyErrorResponse,
)
from src.utils.auth_deps import get_current_user_id
from src.utils.password_utils import hash_token
from src.utils.jwt_utils import create_temp_token
from src.utils.session_utils import normalize_user_agent, save_session

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/auth/passkey", tags=["Passkey"])

_CHALLENGE_TTL = settings.webauthn_challenge_ttl


def _redis_reg_key(user_id: int) -> str:
    return f"webauthn:reg:{user_id}"


def _redis_auth_key(email: str) -> str:
    return f"webauthn:auth:{email.lower()}"


# ──────────────────────────────────────────────
# POST /auth/passkey/register/options
# ──────────────────────────────────────────────
@router.post(
    "/register/options",
    response_model=PasskeyRegisterOptionsResponse,
    summary="Get Passkey Registration Options",
    description=(
        "Generate WebAuthn registration options (challenge, RP info, user info). "
        "The challenge is cached in Redis for 5 minutes. "
        "Requires an authenticated session."
    ),
    responses={
        401: {"description": "Invalid or expired token", "model": PasskeyErrorResponse},
        500: {"description": "Internal server error", "model": PasskeyErrorResponse},
    },
)
async def passkey_register_options(
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        user_id = await get_current_user_id(authorization, db, redis)

        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid or expired token"},
            )

        # Fetch existing passkeys to exclude during registration
        result = await db.execute(
            select(Passkey).where(
                Passkey.user_id == user_id,
                Passkey.is_active == True,  # noqa: E712
            )
        )
        existing = result.scalars().all()
        exclude_credentials = [
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(pk.credential_id),
            )
            for pk in existing
        ]

        options = generate_registration_options(
            rp_id=settings.webauthn_rp_id,
            rp_name=settings.webauthn_rp_name,
            user_id=str(user_id).encode(),
            user_name=account.email,
            user_display_name=account.user_name,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
            exclude_credentials=exclude_credentials,
            timeout=_CHALLENGE_TTL * 1000,
        )

        options_json_str = options_to_json(options)

        # Cache the challenge in Redis
        if redis:
            challenge_b64 = bytes_to_base64url(options.challenge)
            await redis.setex(
                _redis_reg_key(user_id),
                _CHALLENGE_TTL,
                challenge_b64,
            )
        else:
            logger.warning("Redis unavailable — passkey registration challenge cannot be cached")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"message": "Internal server error"},
            )

        logger.info("Passkey register options generated for user_id=%s", user_id)
        return PasskeyRegisterOptionsResponse(options=json.loads(options_json_str))

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("passkey_register_options error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


# ──────────────────────────────────────────────
# POST /auth/passkey/register/verify
# ──────────────────────────────────────────────
@router.post(
    "/register/verify",
    response_model=PasskeyRegisterVerifyResponse,
    summary="Verify Passkey Registration",
    description=(
        "Verify the WebAuthn registration response from the browser. "
        "On success, stores the credential in the database and enables "
        "passkey login for the user."
    ),
    responses={
        400: {"description": "Verification failed", "model": PasskeyErrorResponse},
        401: {"description": "Invalid or expired token", "model": PasskeyErrorResponse},
        500: {"description": "Internal server error", "model": PasskeyErrorResponse},
    },
)
async def passkey_register_verify(
    body: PasskeyRegisterVerifyRequest,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        user_id = await get_current_user_id(authorization, db, redis)

        # Retrieve cached challenge
        if not redis:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"message": "Internal server error"},
            )

        challenge_b64 = await redis.get(_redis_reg_key(user_id))
        if not challenge_b64:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "No pending registration challenge or challenge expired"},
            )

        if isinstance(challenge_b64, bytes):
            challenge_b64 = challenge_b64.decode()

        expected_challenge = base64url_to_bytes(challenge_b64)

        verification = verify_registration_response(
            credential=body.credential,
            expected_challenge=expected_challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            require_user_verification=False,
        )

        # Store credential in DB
        credential_id_b64 = bytes_to_base64url(verification.credential_id)
        public_key_b64 = bytes_to_base64url(verification.credential_public_key)

        passkey = Passkey(
            user_id=user_id,
            credential_id=credential_id_b64,
            public_key=public_key_b64,
            sign_count=verification.sign_count,
            is_active=True,
        )
        db.add(passkey)

        # Enable passkey on the account
        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        account = result.scalar_one_or_none()
        if account:
            account.passkey_enabled = True

        await db.commit()

        # Clean up the challenge from Redis
        await redis.delete(_redis_reg_key(user_id))

        logger.info(
            "Passkey registered for user_id=%s credential_id=%s",
            user_id,
            credential_id_b64[:20] + "...",
        )
        return PasskeyRegisterVerifyResponse(message="Passkey registered successfully")

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("passkey_register_verify error: %s", exc, exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Registration verification failed"},
        )


# ──────────────────────────────────────────────
# POST /auth/passkey/login/options
# ──────────────────────────────────────────────
@router.post(
    "/login/options",
    response_model=PasskeyLoginOptionsResponse,
    summary="Get Passkey Login Options",
    description=(
        "Generate WebAuthn authentication options for passwordless login. "
        "Requires the user's email to look up registered passkey credentials. "
        "No authentication required."
    ),
    responses={
        400: {"description": "Passkey not enabled", "model": PasskeyErrorResponse},
        404: {"description": "User not found", "model": PasskeyErrorResponse},
        500: {"description": "Internal server error", "model": PasskeyErrorResponse},
    },
)
async def passkey_login_options(
    body: PasskeyLoginOptionsRequest,
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        email = body.email.lower()

        result = await db.execute(
            select(Account).where(Account.email == email)
        )
        account = result.scalar_one_or_none()

        if not account or not account.email_verified:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "User not found"},
            )

        if not account.passkey_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Passkey not enabled for this account"},
            )

        # Fetch all active passkeys for this user
        result = await db.execute(
            select(Passkey).where(
                Passkey.user_id == account.user_id,
                Passkey.is_active == True,  # noqa: E712
            )
        )
        passkeys = result.scalars().all()

        if not passkeys:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Passkey not enabled for this account"},
            )

        allow_credentials = [
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(pk.credential_id),
            )
            for pk in passkeys
        ]

        options = generate_authentication_options(
            rp_id=settings.webauthn_rp_id,
            allow_credentials=allow_credentials,
            user_verification=UserVerificationRequirement.PREFERRED,
            timeout=_CHALLENGE_TTL * 1000,
        )

        options_json_str = options_to_json(options)

        # Cache challenge in Redis keyed by email
        if redis:
            challenge_b64 = bytes_to_base64url(options.challenge)
            await redis.setex(
                _redis_auth_key(email),
                _CHALLENGE_TTL,
                challenge_b64,
            )
        else:
            logger.warning("Redis unavailable — passkey login challenge cannot be cached")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"message": "Internal server error"},
            )

        logger.info("Passkey login options generated for email=%s", email)
        return PasskeyLoginOptionsResponse(options=json.loads(options_json_str))

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("passkey_login_options error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


# ──────────────────────────────────────────────
# POST /auth/passkey/login/verify
# ──────────────────────────────────────────────
@router.post(
    "/login/verify",
    response_model=PasskeyLoginVerifyResponse,
    summary="Verify Passkey Login",
    description=(
        "Verify the WebAuthn authentication response from the browser. "
        "On success, creates a new session (refresh token) and returns "
        "the same fields as the normal login endpoint."
    ),
    responses={
        400: {"description": "Verification failed", "model": PasskeyErrorResponse},
        403: {"description": "Account is blocked", "model": PasskeyErrorResponse},
        404: {"description": "User not found", "model": PasskeyErrorResponse},
        500: {"description": "Internal server error", "model": PasskeyErrorResponse},
    },
)
async def passkey_login_verify(
    body: PasskeyLoginVerifyRequest,
    user_agent: str = Header(default="Unknown", alias="User-Agent"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        email = body.email.lower()

        # Retrieve cached challenge
        if not redis:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"message": "Internal server error"},
            )

        challenge_b64 = await redis.get(_redis_auth_key(email))
        if not challenge_b64:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "No pending login challenge or challenge expired"},
            )

        if isinstance(challenge_b64, bytes):
            challenge_b64 = challenge_b64.decode()

        expected_challenge = base64url_to_bytes(challenge_b64)

        # Lookup user
        result = await db.execute(
            select(Account).where(Account.email == email)
        )
        account = result.scalar_one_or_none()

        if not account or not account.email_verified:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "User not found"},
            )

        if account.is_blocked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "Account is blocked"},
            )

        # Find the matching passkey by credential ID
        credential_id_from_browser = body.credential.get("id", "")
        result = await db.execute(
            select(Passkey).where(
                Passkey.user_id == account.user_id,
                Passkey.credential_id == credential_id_from_browser,
                Passkey.is_active == True,  # noqa: E712
            )
        )
        passkey = result.scalar_one_or_none()

        if not passkey:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Authentication verification failed"},
            )

        verification = verify_authentication_response(
            credential=body.credential,
            expected_challenge=expected_challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            credential_public_key=base64url_to_bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=False,
        )

        # Update sign_count and last_used_at
        passkey.sign_count = verification.new_sign_count
        passkey.last_used_at = datetime.now(timezone.utc)

        # Create session (same as normal login)
        refresh_token = create_temp_token()
        token_hashed = hash_token(refresh_token)
        normalized_user_agent = normalize_user_agent(user_agent)
        refresh_token_record = RefreshToken(
            user_id=account.user_id,
            token_hashed=token_hashed,
            user_agent=normalized_user_agent,
            expire_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(refresh_token_record)
        await db.commit()

        await save_session(
            redis,
            token=refresh_token,
            user_id=account.user_id,
            user_agent=normalized_user_agent,
        )

        # Clean up the challenge
        await redis.delete(_redis_auth_key(email))

        logger.info("Passkey login successful for email=%s user_id=%s", email, account.user_id)

        return PasskeyLoginVerifyResponse(
            id=account.user_id,
            name=account.user_name,
            token=refresh_token,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("passkey_login_verify error: %s", exc, exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Authentication verification failed"},
        )
