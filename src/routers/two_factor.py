# This code was completed by GRP Team 2025.11.
"""
Two-Factor Authentication router module.

Endpoints:
  POST /auth/2fa/setup                  – Generate TOTP secret + QR code
  POST /auth/2fa/confirm                – Confirm binding with first TOTP code
  POST /auth/2fa/verify                 – Verify 2FA code during login
  POST /auth/2fa/disable                – Disable 2FA (password required)
  GET  /auth/2fa/status                 – Query 2FA status
  POST /auth/2fa/backup-codes/regenerate – Regenerate backup codes
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import delete as sa_delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.constants import TokenType
from src.config.logger import get_logger
from src.database import (
    Account,
    RefreshToken,
    TempToken,
    TotpBackupCode,
    get_db,
    get_redis,
)
from src.schemas.auth import ErrorResponse
from src.schemas.two_factor import (
    Confirm2FARequest,
    Confirm2FAResponse,
    Disable2FARequest,
    Disable2FAResponse,
    RegenerateBackupCodesRequest,
    RegenerateBackupCodesResponse,
    Setup2FAResponse,
    TwoFAStatusResponse,
    Verify2FARequest,
    Verify2FAResponse,
)
from src.utils import (
    create_temp_token,
    hash_token,
    hash_password,
    verify_password,
    generate_totp_secret,
    get_totp_uri,
    verify_totp_code,
    generate_qr_code_base64,
    encrypt_secret,
    decrypt_secret,
    generate_backup_codes,
    check_totp_replay,
    normalize_user_agent,
)
from src.utils.auth_deps import get_current_user_id
from src.utils.session_utils import save_session

logger = get_logger(__name__)

router = APIRouter(prefix="/auth/2fa", tags=["Two-Factor Authentication"])

# Redis key helpers
_SETUP_PREFIX = "2fa_setup:"
_SETUP_TTL = 300  # 5 minutes


# ──────────────────────────── helpers ────────────────────────────

async def _require_user(
    authorization: str,
    db: AsyncSession,
    redis: Optional[Redis],
) -> Account:
    """Resolve Authorization header → Account object (or 401)."""
    user_id = await get_current_user_id(authorization, db, redis)
    result = await db.execute(select(Account).where(Account.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        )
    return user


def _is_backup_code_format(code: str) -> bool:
    """Return True if code looks like a backup code (8-char hex)."""
    return len(code) == 8 and all(c in "0123456789ABCDEFabcdef" for c in code)


# ──────────────────────────── POST /setup ────────────────────────────

@router.post(
    "/setup",
    response_model=Setup2FAResponse,
    summary="Setup 2FA",
    responses={
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def setup_2fa(
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    user = await _require_user(authorization, db, redis)

    if user.is_2fa_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "2FA is already enabled"},
        )

    # Generate TOTP secret and backup codes
    secret = generate_totp_secret()
    backup_codes = generate_backup_codes()
    totp_uri = get_totp_uri(secret, user.email)
    qr_base64 = generate_qr_code_base64(totp_uri)

    # Store in Redis temporarily (5 min)
    if redis is not None:
        setup_key = f"{_SETUP_PREFIX}{user.user_id}"
        await redis.set(
            setup_key,
            json.dumps({"secret": secret, "backup_codes": backup_codes}),
            ex=_SETUP_TTL,
        )
    else:
        logger.warning("Redis unavailable — 2FA setup data cannot be cached")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Service temporarily unavailable, please try again later"},
        )

    logger.info(f"2FA setup initiated for user_id={user.user_id}")

    return Setup2FAResponse(
        totp_uri=totp_uri,
        qr_code_base64=qr_base64,
        backup_codes=backup_codes,
    )


# ──────────────────────────── POST /confirm ────────────────────────────

@router.post(
    "/confirm",
    response_model=Confirm2FAResponse,
    summary="Confirm 2FA binding",
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def confirm_2fa(
    request: Confirm2FARequest,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    user = await _require_user(authorization, db, redis)

    if user.is_2fa_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "2FA is already enabled"},
        )

    # Retrieve pending setup from Redis
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Service temporarily unavailable"},
        )

    setup_key = f"{_SETUP_PREFIX}{user.user_id}"
    raw = await redis.get(setup_key)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "2FA setup not found or expired, please call /auth/2fa/setup first"},
        )

    setup_data = json.loads(raw)
    secret = setup_data["secret"]
    backup_codes: list[str] = setup_data["backup_codes"]

    # Verify the TOTP code
    if not verify_totp_code(secret, request.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Invalid TOTP code"},
        )

    # Replay protection
    if await check_totp_replay(redis, user.user_id, request.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "TOTP code already used, please wait for a new code"},
        )

    # Persist: encrypt secret → Account, hash backup codes → TotpBackupCode
    user.totp_secret_encrypted = encrypt_secret(secret)
    user.is_2fa_enabled = True

    for code in backup_codes:
        db.add(TotpBackupCode(
            user_id=user.user_id,
            code_hashed=hash_password(code),
        ))

    await db.commit()

    # Clean up Redis
    await redis.delete(setup_key)

    logger.info(f"2FA enabled for user_id={user.user_id}")
    return Confirm2FAResponse(message="2FA enabled successfully")


# ──────────────────────────── POST /verify ────────────────────────────

@router.post(
    "/verify",
    response_model=Verify2FAResponse,
    summary="Verify 2FA code during login",
    responses={
        401: {"model": ErrorResponse},
    },
)
async def verify_2fa(
    request: Verify2FARequest,
    temp_token: str = Header(..., alias="Temp-Token"),
    user_agent: str = Header(default="Unknown", alias="User-Agent"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    # Look up 2fa_verify temp token
    temp_token_hashed = hash_token(temp_token)
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token_hashed,
            TempToken.token_type == TokenType.TWO_FACTOR_VERIFY,
        )
    )
    token_record = result.scalar_one_or_none()

    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired temp token"},
        )

    # Check expiry
    if datetime.now(timezone.utc) > token_record.expire_at:
        await db.delete(token_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired temp token"},
        )

    # Load user
    result = await db.execute(
        select(Account).where(Account.user_id == token_record.user_id)
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_2fa_enabled or not user.totp_secret_encrypted:
        await db.delete(token_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired temp token"},
        )

    code = request.code.strip()
    verified = False

    # Try TOTP code first (6 digits)
    if not _is_backup_code_format(code):
        secret = decrypt_secret(user.totp_secret_encrypted)
        verified = verify_totp_code(secret, code)
        # Replay protection
        if verified and await check_totp_replay(redis, user.user_id, code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "TOTP code already used, please wait for a new code"},
            )
    else:
        # Try as backup code
        result = await db.execute(
            select(TotpBackupCode).where(
                TotpBackupCode.user_id == user.user_id,
                TotpBackupCode.is_used == False,  # noqa: E712
            )
        )
        for bc in result.scalars().all():
            if verify_password(code.upper(), bc.code_hashed):
                bc.is_used = True
                verified = True
                break

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid 2FA code"},
        )

    # 2FA passed – create refresh token (same as normal login)
    refresh_token = create_temp_token()
    normalized_user_agent = normalize_user_agent(user_agent)
    refresh_token_record = RefreshToken(
        user_id=user.user_id,
        token_hashed=hash_token(refresh_token),
        user_agent=normalized_user_agent,
        expire_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(refresh_token_record)
    await db.delete(token_record)  # consume temp token
    await db.commit()

    # Cache session in Redis
    await save_session(
        redis,
        token=refresh_token,
        user_id=user.user_id,
        user_agent=normalized_user_agent,
    )

    logger.info(f"2FA verification successful for user_id={user.user_id}")

    return Verify2FAResponse(
        id=user.user_id,
        name=user.user_name,
        token=refresh_token,
    )


# ──────────────────────────── POST /disable ────────────────────────────

@router.post(
    "/disable",
    response_model=Disable2FAResponse,
    summary="Disable 2FA",
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
    },
)
async def disable_2fa(
    request: Disable2FARequest,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    user = await _require_user(authorization, db, redis)

    if not user.is_2fa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "2FA is not enabled"},
        )

    # Verify password
    if not verify_password(request.password, user.password_hashed):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Incorrect password"},
        )

    # Clear 2FA data
    user.is_2fa_enabled = False
    user.totp_secret_encrypted = None

    # Delete all backup codes
    await db.execute(
        sa_delete(TotpBackupCode).where(TotpBackupCode.user_id == user.user_id)
    )

    await db.commit()

    logger.info(f"2FA disabled for user_id={user.user_id}")
    return Disable2FAResponse(message="2FA disabled successfully")


# ──────────────────────────── GET /status ────────────────────────────

@router.get(
    "/status",
    response_model=TwoFAStatusResponse,
    summary="Get 2FA status",
    responses={
        401: {"model": ErrorResponse},
    },
)
async def get_2fa_status(
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    user = await _require_user(authorization, db, redis)

    remaining = 0
    if user.is_2fa_enabled:
        result = await db.execute(
            select(func.count()).select_from(TotpBackupCode).where(
                TotpBackupCode.user_id == user.user_id,
                TotpBackupCode.is_used == False,  # noqa: E712
            )
        )
        remaining = result.scalar() or 0

    return TwoFAStatusResponse(
        is_2fa_enabled=user.is_2fa_enabled,
        backup_codes_remaining=remaining,
    )


# ──────────────────────── POST /backup-codes/regenerate ──────────────────────

@router.post(
    "/backup-codes/regenerate",
    response_model=RegenerateBackupCodesResponse,
    summary="Regenerate backup codes",
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
    },
)
async def regenerate_backup_codes(
    request: RegenerateBackupCodesRequest,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    user = await _require_user(authorization, db, redis)

    if not user.is_2fa_enabled or not user.totp_secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "2FA is not enabled"},
        )

    # Verify TOTP code
    secret = decrypt_secret(user.totp_secret_encrypted)
    if not verify_totp_code(secret, request.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Invalid TOTP code"},
        )

    # Replay protection
    if await check_totp_replay(redis, user.user_id, request.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "TOTP code already used, please wait for a new code"},
        )

    # Delete old backup codes
    await db.execute(
        sa_delete(TotpBackupCode).where(TotpBackupCode.user_id == user.user_id)
    )

    # Generate and persist new codes
    new_codes = generate_backup_codes()
    for code in new_codes:
        db.add(TotpBackupCode(
            user_id=user.user_id,
            code_hashed=hash_password(code),
        ))

    await db.commit()

    logger.info(f"Backup codes regenerated for user_id={user.user_id}")
    return RegenerateBackupCodesResponse(backup_codes=new_codes)
