"""
Authentication router module
Contains authentication related endpoints such as user login
"""
from fastapi import APIRouter, HTTPException, Header, status, Depends
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from src.schemas.auth import (
    LoginRequest,
    LoginResponse,
    Login2FARequiredResponse,
    LogoutResponse,
    LogoutAllResponse,
    SignUpRequest,
    SignUpResponse,
    VerifySignupEmailRequest,
    VerifySignupEmailResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    VerifyResetCodeRequest,
    VerifyResetCodeResponse,
    ResendSignupCodeResponse,
    ResendResetCodeResponse,
    RateLimitResponse,
    ConfirmResetPasswordRequest,
    ConfirmResetPasswordResponse,
    GetUserInfoResponse,
    DeviceSession,
    DevicesResponse,
    LogoutDeviceResponse,
    DeleteAccountResponse,
    VerifyDeleteRequest,
    DeleteVerifyResponse,
    ErrorResponse,
)
from src.utils import (
    create_access_token,
    verify_token,
    create_temp_token,
    generate_verification_code,
    hash_password,
    hash_token,
    verify_password,
    send_verification_email,
    get_token_data,
    decrypt_secret,
    verify_totp_code,
    check_totp_replay,
)
from redis.asyncio import Redis
from src.config.logger import get_logger
from src.config.constants import TokenType, UserType
from src.database import get_db, get_redis, Account, UserProfile, TempToken, RefreshToken, TotpBackupCode
from src.utils.session_utils import save_session, get_session, delete_session, delete_session_by_hash, delete_all_user_sessions
from src.utils.auth_deps import get_current_user_id
from user_agents import parse as parse_ua

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


async def _reset_password_with_code(
    request: ConfirmResetPasswordRequest,
    temp_token: str,
    db: AsyncSession,
) -> ConfirmResetPasswordResponse:
    """
    Internal helper to verify reset code and update password
    """
    logger.info("Password reset confirmation attempt with temp_token")
    
    temp_token_hashed = hash_token(temp_token)

    # Check if temp token exists with correct type
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token_hashed,
            TempToken.token_type == TokenType.PASSWORD_RESET
        )
    )
    reset_record = result.scalar_one_or_none()
    
    if not reset_record:
        logger.warning("Password reset failed: Invalid temp token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Check if expired
    if datetime.now(timezone.utc) > reset_record.expire_at:
        logger.warning("Password reset failed: Expired token")
        await db.delete(reset_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Verify code against stored hash
    if not reset_record.verification_code_hashed or not verify_password(request.code, reset_record.verification_code_hashed):
        logger.warning("Password reset failed: Invalid verification code")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Find user and update password
    result = await db.execute(
        select(Account).where(Account.user_id == reset_record.user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        logger.error(f"Password reset failed: User not found for user_id: {reset_record.user_id}")
        await db.delete(reset_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found"}
        )
    
    # Update password
    user.password_hashed = hash_password(request.new_password)
    await db.delete(reset_record)  # Clean up reset record
    await db.commit()
    
    logger.info(f"Password reset successful for user: {user.email}")
    
    return ConfirmResetPasswordResponse(message="Password reset successfully")


# ============ Login ============
@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="User Login",
    responses={
        200: {"description": "Login successful", "model": LoginResponse},
        202: {"description": "2FA verification required", "model": Login2FARequiredResponse},
        401: {"description": "Incorrect password", "model": ErrorResponse},
        404: {"description": "User not found", "model": ErrorResponse}
    }
)
async def login(
    login_data: LoginRequest,
    user_agent: str = Header(default="Unknown", alias="User-Agent"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    User login endpoint
    
    - **email**: User email address (required)
    - **password**: User password (required)
    """
    try:
        logger.info(f"Login attempt for email: {login_data.email}")
        
        # Normalize email to lowercase
        email = login_data.email.lower()
        
        # Query user by email
        result = await db.execute(
            select(Account).where(Account.email == email)
        )
        user = result.scalar_one_or_none()
        
        # Treat non-existent and unverified accounts the same
        if not user or not user.email_verified:
            logger.warning(f"User not found: {email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "User not found"}
            )
        
        # Check if account is blocked
        if user.is_blocked:
            logger.warning(f"Blocked account login attempt: {email}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "Account is blocked"}
            )
        
        # Verify password
        if not verify_password(login_data.password, user.password_hashed):
            logger.warning(f"Incorrect password for user: {email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Incorrect password"}
            )
        
        # ── 2FA check ──
        if user.is_2fa_enabled:
            two_fa_temp_token = create_temp_token()
            two_fa_record = TempToken(
                user_id=user.user_id,
                token_hashed=hash_token(two_fa_temp_token),
                token_type=TokenType.TWO_FACTOR_VERIFY,
                expire_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
            db.add(two_fa_record)
            await db.commit()

            logger.info(f"2FA required for user: {email}")
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=Login2FARequiredResponse(
                    temp_token=two_fa_temp_token,
                ).model_dump(),
            )
        # ── End 2FA check ──

        # Create refresh token and store in database
        refresh_token = create_temp_token()
        token_hashed = hash_token(refresh_token)
        refresh_token_record = RefreshToken(
            user_id=user.user_id,
            token_hashed=token_hashed,
            user_agent=user_agent[:100],  # Limit to 100 chars
            expire_at=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db.add(refresh_token_record)
        await db.commit()

        # Cache session in Redis (non-fatal if Redis is unavailable)
        await save_session(
            redis,
            token=refresh_token,
            user_id=user.user_id,
            user_agent=user_agent[:100],
        )

        logger.info(f"Login successful for user: {email}")

        return LoginResponse(
            id=user.user_id,
            name=user.user_name,
            token=refresh_token  # Return refresh token as session token
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"}
        )


# ============ Logout ============
@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
    summary="User Logout",
    responses={
        200: {"description": "Logout successful", "model": LogoutResponse},
        401: {"description": "Invalid or expired token", "model": ErrorResponse}
    }
)
async def logout(
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    User logout endpoint - deletes the refresh token from database
    
    - **Authorization**: Bearer token (refresh token) in header
    """
    try:
        # Extract token from Authorization header
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid authorization header format"}
            )
        
        token = authorization.replace("Bearer ", "")
        
        logger.info("Logout attempt with token")

        refresh_token_record = None

        # 1. Try Redis cache first (key is HMAC-SHA256(token), same as DB token_hashed)
        session_data = await get_session(redis, token)

        if session_data:
            # Cache hit: recompute digest to do exact DB query
            result = await db.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hashed == hash_token(token)
                )
            )
            refresh_token_record = result.scalar_one_or_none()

        if not refresh_token_record:
            # Cache miss: direct DB query using HMAC-SHA256 (O(1) index lookup)
            result = await db.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hashed == hash_token(token)
                )
            )
            refresh_token_record = result.scalar_one_or_none()

        if not refresh_token_record:
            logger.warning("Logout failed: Token not found")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid or expired token"}
            )

        # Delete from DB and Redis
        await db.delete(refresh_token_record)
        await db.commit()
        await delete_session(redis, token)

        logger.info(f"Logout successful for user_id: {refresh_token_record.user_id}")

        return LogoutResponse(message="Logged out successfully")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"}
        )


# ============ Sign Up ============
@router.post(
    "/signup",
    response_model=SignUpResponse,
    responses={
        409: {"model": ErrorResponse, "description": "Account exists"},
    },
)
async def signup(request: SignUpRequest, db: AsyncSession = Depends(get_db)):
    """
    User signup endpoint
    
    - **name**: User's display name
    - **email**: User's email address
    - **password**: User's password
    
    Note: New users are automatically assigned user_type=1 (student).
    
    Returns temp_token for email verification
    """
    logger.info(f"Signup attempt for email: {request.email}")
    
    # Normalize email to lowercase
    email = request.email.lower()
    
    # Check if account already exists
    result = await db.execute(select(Account).where(Account.email == email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        if existing_user.email_verified:
            # Already verified account — cannot re-register
            logger.warning(f"Signup failed: Verified account already exists for email: {email}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Account exists"}
            )
        else:
            # Unverified account — allow re-registration by updating credentials
            logger.info(f"Re-registration for unverified email: {email}")
            existing_user.user_name = request.name
            existing_user.password_hashed = hash_password(request.password)

            # Clean up any old email_verify temp tokens for this user
            await db.execute(
                delete(TempToken).where(
                    TempToken.user_id == existing_user.user_id,
                    TempToken.token_type == TokenType.EMAIL_VERIFY
                )
            )

            new_account = existing_user
    else:
        # Create new account (not yet verified)
        new_account = Account(
            user_name=request.name,
            email=email,
            password_hashed=hash_password(request.password),
            user_type=1,  # Default: student user type
            email_verified=False,
        )
        db.add(new_account)

    await db.commit()
    await db.refresh(new_account)
    
    # Generate temp token and verification code
    temp_token = create_temp_token()
    verification_code = generate_verification_code()

    # Create temp token for email verification with hashed verification code
    temp_token_record = TempToken(
        user_id=new_account.user_id,
        token_hashed=hash_token(temp_token),
        token_type=TokenType.EMAIL_VERIFY,
        verification_code_hashed=hash_password(verification_code),  # Hash the verification code
        expire_at=datetime.now(timezone.utc) + timedelta(minutes=5)  # 5 minute expiry
    )
    
    db.add(temp_token_record)
    await db.commit()
    
    # Send verification code via email
    logger.info(f"Signup temp token created for email: {email}")
    email_sent = await send_verification_email(
        to_email=email,
        verification_code=verification_code,
        name=request.name,  # Use provided name
        email_type="signup"
    )
    
    if not email_sent:
        logger.warning(f"Failed to send verification email to {email}, but signup record created")
    
    return SignUpResponse(temp_token=temp_token)


# ============ Resend Signup Verification Code ============
@router.post(
    "/signup/resend",
    response_model=ResendSignupCodeResponse,
    summary="Resend Signup Verification Code",
    responses={
        401: {"model": ErrorResponse, "description": "Token expired or invalid"},
        429: {"model": RateLimitResponse, "description": "Too many requests"},
    },
)
async def resend_signup_code(
    temp_token: str = Header(..., alias="Temp-Token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Resend verification code to email for signup process.

    - **Temp-Token**: Temporary token from /auth/signup endpoint (in header)

    Returns success message if code is resent successfully.
    """
    logger.info("Resend signup verification code attempt")

    temp_token_hashed = hash_token(temp_token)

    # Look up the email_verify temp token
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token_hashed,
            TempToken.token_type == TokenType.EMAIL_VERIFY,
        )
    )
    token_record = result.scalar_one_or_none()

    if not token_record:
        logger.warning("Resend signup code failed: Invalid temp token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Token expired or invalid"},
        )

    now = datetime.now(timezone.utc)

    # Check if expired
    if now > token_record.expire_at:
        logger.warning("Resend signup code failed: Expired token")
        await db.delete(token_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Token expired or invalid"},
        )

    # Rate limit: 60 seconds between resends
    if token_record.created_at:
        retry_after = 60 - int((now - token_record.created_at).total_seconds())
        if retry_after > 0:
            logger.warning("Resend signup code throttled")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Too many requests. Please wait before requesting again.",
                    "retryAfter": retry_after,
                },
            )

    # Get the associated (still blocked) account for name and email
    result = await db.execute(
        select(Account).where(Account.user_id == token_record.user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        logger.error(f"Resend signup code failed: User not found for user_id: {token_record.user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Token expired or invalid"},
        )

    # Generate new code and send email
    verification_code = generate_verification_code()
    email_sent = await send_verification_email(
        to_email=user.email,
        verification_code=verification_code,
        name=user.user_name,
        email_type="signup",
    )

    if not email_sent:
        logger.warning(f"Failed to resend signup verification email to {user.email}")

    # Update created_at (rate-limit clock) and hash the new code
    token_record.created_at = now
    token_record.verification_code_hashed = hash_password(verification_code)
    await db.commit()

    logger.info(f"Signup verification code resent for user_id: {user.user_id}")
    return ResendSignupCodeResponse(message="Verification code resent successfully")


# ============ Verify Signup Email ============
async def _verify_signup_email_impl(
    request: VerifySignupEmailRequest,
    temp_token: str,
    user_agent: str,
    db: AsyncSession
) -> VerifySignupEmailResponse:
    """
    Internal implementation for signup email verification
    
    - **temp_token**: Temporary token from signup
    - **code**: Verification code sent to email
    
    Returns JWT token on successful verification and activates the user account
    """
    logger.info(f"Signup email verification attempt with temp_token")

    temp_token_hashed = hash_token(temp_token)
    
    # Check if temp token exists with correct type
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token_hashed,
            TempToken.token_type == TokenType.EMAIL_VERIFY
        )
    )
    verification = result.scalar_one_or_none()
    
    if not verification:
        logger.warning("Signup email verification failed: Invalid temp token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code"}
        )
    
    # Check if expired
    if datetime.now(timezone.utc) > verification.expire_at:
        logger.warning("Signup email verification failed: Expired token")
        await db.delete(verification)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code"}
        )
    
    # Verify code against stored hash
    if not verification.verification_code_hashed or not verify_password(request.code, verification.verification_code_hashed):
        logger.warning("Signup email verification failed: Invalid verification code")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code"}
        )
    
    # Get user account and activate it
    result = await db.execute(
        select(Account)
        .options(selectinload(Account.profile))
        .where(Account.user_id == verification.user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        logger.error(f"Signup verification failed: User not found for user_id: {verification.user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found"}
        )
    
    # Mark email as verified
    user.email_verified = True
    
    # Create user profile if not exists (in case of re-registration)
    if not user.profile:
        user_profile = UserProfile(
            user_id=user.user_id,
            basic_info={}  # Empty JSONB object
        )
        db.add(user_profile)
    
    await db.delete(verification)
    await db.commit()
    await db.refresh(user)
    
    # Create refresh token and store in database
    refresh_token = create_temp_token()
    refresh_token_record = RefreshToken(
        user_id=user.user_id,
        token_hashed=hash_token(refresh_token),
        user_agent=user_agent[:100],  # Limit to 100 chars
        expire_at=datetime.now(timezone.utc) + timedelta(days=30)
    )
    db.add(refresh_token_record)
    await db.commit()
    
    logger.info(f"Signup email verified and user activated with ID: {user.user_id}")
    
    return VerifySignupEmailResponse(
        id=user.user_id,
        name=user.user_name,
        token=refresh_token  # Return refresh token as session token
    )


@router.post(
    "/verify",
    response_model=VerifySignupEmailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse, "description": "Wrong code"},
    },
)
async def verify(
    request: VerifySignupEmailRequest,
    temp_token: str = Header(..., alias="Temp-Token"),
    user_agent: str = Header(default="Unknown", alias="User-Agent"),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify signup email (short alias for /verify-signup-email)
    
    - **temp_token**: Temporary token from signup (in header)
    - **code**: Verification code sent to email
    
    Returns JWT token on successful verification and activates the user account
    """
    return await _verify_signup_email_impl(request, temp_token, user_agent, db)


@router.post(
    "/verify-signup-email",
    response_model=VerifySignupEmailResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse, "description": "Wrong code"},
    },
)
async def verify_signup_email(
    request: VerifySignupEmailRequest,
    temp_token: str = Header(..., alias="Temp-Token"),
    user_agent: str = Header(default="Unknown", alias="User-Agent"),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify signup email (full endpoint path)
    
    - **temp_token**: Temporary token from signup (in header)
    - **code**: Verification code sent to email
    
    Returns JWT token on successful verification and activates the user account
    """
    return await _verify_signup_email_impl(request, temp_token, user_agent, db)


# ============ Reset Password ============
@router.post(
    "/reset",
    response_model=ResetPasswordResponse,
    responses={
        404: {"model": ErrorResponse, "description": "No account record for this email"},
    },
)
async def reset_password(request: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """
    Password reset request endpoint
    
    - **email**: User's email address
    
    Returns temp_token for password reset verification
    """
    logger.info(f"Password reset request for email: {request.email}")
    
    # Normalize email to lowercase
    email = request.email.lower()
    
    # Check if user exists
    result = await db.execute(select(Account).where(Account.email == email))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"Password reset failed: No account for email: {email}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "No account record for this email"}
        )
    
    # Generate temp token and reset code
    temp_token = create_temp_token()
    reset_code = generate_verification_code()
    
    # Create password reset record with hashed verification code
    reset_record = TempToken(
        user_id=user.user_id,
        token_hashed=hash_token(temp_token),
        token_type=TokenType.PASSWORD_RESET,
        verification_code_hashed=hash_password(reset_code),  # Hash the reset code
        expire_at=datetime.now(timezone.utc) + timedelta(minutes=5)  # 5 minute expiry
    )
    
    db.add(reset_record)
    await db.commit()
    
    # Send reset code via email
    logger.info(f"Password reset temp token created for email: {email}")
    email_sent = await send_verification_email(
        to_email=email,
        verification_code=reset_code,
        name=email.split('@')[0],  # Use email prefix as name
        email_type="reset"
    )
    
    if not email_sent:
        logger.warning(f"Failed to send reset code email to {email}, but reset record created")
    
    return ResetPasswordResponse(temp_token=temp_token)


# ============ Verify Reset Code ============
@router.post(
    "/verify-reset-code",
    response_model=VerifyResetCodeResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Wrong code or expired token"},
    },
)
async def verify_reset_code(
    request: VerifyResetCodeRequest,
    temp_token: str = Header(..., alias="temp_token"),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify password reset code
    
    - **temp_token**: Temporary token from reset-password (in header)
    - **code**: Reset code sent to email
    
    Returns success message if code is valid. Use confirm-reset-password to actually change the password.
    """
    logger.info(f"Password reset code verification attempt with temp_token")

    temp_token_hashed = hash_token(temp_token)
    
    # Check if temp token exists with correct type
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token_hashed,
            TempToken.token_type == TokenType.PASSWORD_RESET
        )
    )
    reset_record = result.scalar_one_or_none()
    
    if not reset_record:
        logger.warning("Reset code verification failed: Invalid temp token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Check if expired
    if datetime.now(timezone.utc) > reset_record.expire_at:
        logger.warning("Reset code verification failed: Expired token")
        await db.delete(reset_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Verify code against stored hash
    if not reset_record.verification_code_hashed or not verify_password(request.code, reset_record.verification_code_hashed):
        logger.warning("Reset code verification failed: Invalid verification code")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    logger.info(f"Reset code verified successfully for user_id: {reset_record.user_id}")
    
    return VerifyResetCodeResponse(message="Code verified successfully")


# ============ Resend Reset Code ============
@router.post(
    "/reset/resend",
    response_model=ResendResetCodeResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Token expired or invalid"},
        429: {"model": RateLimitResponse, "description": "Too many requests"},
    },
)
async def resend_reset_code(
    temp_token: str = Header(..., alias="Temp-Token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Resend password reset verification code

    - **Temp-Token**: Temporary token from /auth/reset endpoint (in header)

    Returns success message if code is resent successfully.
    """
    logger.info("Resend reset code attempt with temp-token")

    temp_token_hashed = hash_token(temp_token)

    # Check if temp token exists with correct type
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token_hashed,
            TempToken.token_type == TokenType.PASSWORD_RESET,
        )
    )
    reset_record = result.scalar_one_or_none()

    if not reset_record:
        logger.warning("Resend reset code failed: Invalid temp token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Token expired or invalid"},
        )

    now = datetime.now(timezone.utc)

    # Check if expired
    if now > reset_record.expire_at:
        logger.warning("Resend reset code failed: Expired token")
        await db.delete(reset_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Token expired or invalid"},
        )

    # Rate limit: 60 seconds between resends
    if reset_record.created_at:
        retry_after = 60 - int((now - reset_record.created_at).total_seconds())
        if retry_after > 0:
            logger.warning("Resend reset code throttled")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Too many requests. Please wait before requesting again.",
                    "retryAfter": retry_after,
                },
            )

    # Find user email
    result = await db.execute(
        select(Account).where(Account.user_id == reset_record.user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        logger.error(f"Resend reset code failed: User not found for user_id: {reset_record.user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Token expired or invalid"},
        )

    # Generate and send new reset code
    reset_code = generate_verification_code()
    email_sent = await send_verification_email(
        to_email=user.email,
        verification_code=reset_code,
        name=user.email.split("@")[0],
        email_type="reset",
    )

    if not email_sent:
        logger.warning(f"Failed to resend reset code email to {user.email}")

    # Update created_at and verification_code_hashed for the new code
    reset_record.created_at = now
    reset_record.verification_code_hashed = hash_password(reset_code)
    await db.commit()

    return ResendResetCodeResponse(message="Verification code resent successfully")


# ============ Confirm Reset Password ============
@router.post(
    "/confirm-reset-password",
    response_model=ConfirmResetPasswordResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Wrong code or expired token"},
    },
)
async def confirm_reset_password(
    request: ConfirmResetPasswordRequest,
    temp_token: str = Header(..., alias="temp_token"),
    db: AsyncSession = Depends(get_db)
):
    """
    Confirm password reset with verification code and set new password
    
    - **temp_token**: Temporary token from reset-password (in header)
    - **code**: Reset code sent to email
    - **new_password**: New password to set
    
    Returns success message on password reset
    """
    return await _reset_password_with_code(request, temp_token, db)


# ============ Reset Password - Verify & Update (Combined) ============
@router.post(
    "/reset/verify",
    response_model=ConfirmResetPasswordResponse,
    summary="Reset Password - Verification",
    responses={
        401: {"model": ErrorResponse, "description": "Wrong code or expired token"},
    },
)
async def reset_verify(
    request: ConfirmResetPasswordRequest,
    temp_token: str = Header(..., alias="Temp-Token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Verify password reset code and update user password in one step.
    
    This is a combined endpoint that verifies the reset code and sets a new password.
    
    **Request Parameters:**
    - **temp_token** (header): Temporary token from reset-password endpoint
    - **code** (body): Verification code sent to user's email
    - **newPassword** (body): New password to set (must be 8+ characters with letters and numbers)
    
    **Returns:** Success message on password reset
    """
    return await _reset_password_with_code(request, temp_token, db)


# ============ Get User Info ============
@router.get(
    "/settings/info",
    response_model=GetUserInfoResponse,
    status_code=status.HTTP_200_OK,
    summary="Get User Info",
    responses={
        200: {"description": "Successfully retrieved user info", "model": GetUserInfoResponse},
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        404: {"description": "User not found", "model": ErrorResponse},
    },
)
async def get_user_info(
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Returns the email, name and user type of the currently authenticated user.

    - **Authorization**: Bearer token (refresh token) in header
    """
    user_id = await get_current_user_id(authorization, db, redis)

    result = await db.execute(
        select(Account).where(Account.user_id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        logger.error(f"Get user info failed: User not found for user_id: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found"},
        )

    return GetUserInfoResponse(
        email=user.email,
        name=user.user_name,
        user_type=user.user_type,
    )


# ============ Logout All Devices ============
@router.post(
    "/settings/logout-all",
    response_model=LogoutAllResponse,
    status_code=status.HTTP_200_OK,
    summary="Logout All Devices",
    responses={
        200: {"description": "All sessions revoked successfully", "model": LogoutAllResponse},
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def logout_all_devices(
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Invalidates all active sessions for the current user across all devices.

    - **Authorization**: Bearer token (refresh token) in header
    """
    try:
        user_id = await get_current_user_id(authorization, db, redis)

        # Always revoke all sessions first, even if Account row is missing
        delete_result = await db.execute(
            delete(RefreshToken).where(RefreshToken.user_id == user_id)
        )
        db_revoked = delete_result.rowcount
        await db.commit()

        if redis:
            await delete_all_user_sessions(redis, user_id)

        # Verify user exists (log anomaly but still return success since sessions are revoked)
        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            logger.error(f"Logout all: Account not found for user_id: {user_id}, revoked {db_revoked} orphaned sessions")

        logger.info(f"Logout all devices successful for user_id: {user_id}, revoked {db_revoked} sessions")

        return LogoutAllResponse(
            message="All devices have been logged out",
            revoked_count=db_revoked,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout all devices error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


def _parse_device_type(ua) -> str:
    """Map user_agents flags to a device_type string."""
    if ua.is_bot:
        return "Bot"
    if ua.is_tablet:
        return "Tablet"
    if ua.is_mobile:
        return "Mobile"
    if ua.is_pc:
        return "PC"
    return "Unknown"


# ============ Delete Account ============
@router.delete(
    "/delete",
    response_model=DeleteAccountResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete Account",
    responses={
        200: {"description": "Deletion initiated", "model": DeleteAccountResponse},
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
    },
)
async def delete_account(
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Initiate account deletion for the currently authenticated user.

    - If 2FA is enabled, returns `verification: "2fa"`.
    - Otherwise, sends a verification code to email and returns `verification: "email"`.
    """
    try:
        user_id = await get_current_user_id(authorization, db, redis)

        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid or expired token"},
            )

        # Create temp token for deletion verification
        temp_token_raw = create_temp_token()
        temp_record = TempToken(
            user_id=user.user_id,
            token_hashed=hash_token(temp_token_raw),
            token_type=TokenType.DELETE_ACCOUNT,
            expire_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        if user.is_2fa_enabled:
            db.add(temp_record)
            await db.commit()
            logger.info(f"Delete account initiated (2fa) for user_id={user.user_id}")
            return DeleteAccountResponse(temp_token=temp_token_raw, verification="2fa")

        # No 2FA — send email verification code
        verification_code = generate_verification_code()
        temp_record.verification_code_hashed = hash_password(verification_code)
        db.add(temp_record)
        await db.commit()

        email_sent = await send_verification_email(
            to_email=user.email,
            verification_code=verification_code,
            name=user.user_name,
            email_type="delete",
        )

        if not email_sent:
            await db.delete(temp_record)
            await db.commit()
            logger.error(f"Failed to send delete verification email for user_id={user.user_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"message": "Failed to send verification email. Please try again later."},
            )

        logger.info(f"Delete account initiated (email) for user_id={user.user_id}")
        return DeleteAccountResponse(temp_token=temp_token_raw, verification="email")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete account error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


def _is_backup_code_format(code: str) -> bool:
    """Return True if code looks like a backup code (8-char hex)."""
    return len(code) == 8 and all(c in "0123456789ABCDEFabcdef" for c in code)


# ============ Delete Account - Verify 2FA ============
@router.post(
    "/delete/2fa",
    response_model=DeleteVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify 2FA for Account Deletion",
    responses={
        200: {"description": "Account deleted successfully", "model": DeleteVerifyResponse},
        400: {"description": "Invalid verification code", "model": ErrorResponse},
        401: {"description": "Invalid or expired temp token", "model": ErrorResponse},
    },
)
async def verify_delete_2fa(
    request: VerifyDeleteRequest,
    temp_token: str = Header(..., alias="Temp-Token"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Complete account deletion by verifying a TOTP code or backup code.
    """
    try:
        temp_token_hashed = hash_token(temp_token)
        result = await db.execute(
            select(TempToken).where(
                TempToken.token_hashed == temp_token_hashed,
                TempToken.token_type == TokenType.DELETE_ACCOUNT,
            )
        )
        token_record = result.scalar_one_or_none()

        if not token_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid or expired token"},
            )

        if datetime.now(timezone.utc) > token_record.expire_at:
            await db.delete(token_record)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid or expired token"},
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
                detail={"message": "Invalid or expired token"},
            )

        code = request.code.strip()
        verified = False

        if not _is_backup_code_format(code):
            secret = decrypt_secret(user.totp_secret_encrypted)
            verified = verify_totp_code(secret, code)
            if verified and redis and await check_totp_replay(redis, user.user_id, code):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"message": "TOTP code already used, please wait for a new code"},
                )
        else:
            result = await db.execute(
                select(TotpBackupCode).where(
                    TotpBackupCode.user_id == user.user_id,
                    TotpBackupCode.is_used == False,  # noqa: E712
                )
            )
            for bc in result.scalars().all():
                if verify_password(code.upper(), bc.code_hashed):
                    verified = True
                    break

        if not verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Invalid verification code"},
            )

        # Delete all sessions from Redis
        if redis:
            await delete_all_user_sessions(redis, user.user_id)

        # Delete account (CASCADE handles all related data)
        await db.delete(token_record)
        await db.delete(user)
        await db.commit()

        logger.info(f"Account deleted via 2FA for user_id={user.user_id}")
        return DeleteVerifyResponse(message="Account deleted successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete account 2FA verify error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


# ============ Delete Account - Verify Email ============
@router.post(
    "/delete/email",
    response_model=DeleteVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify Email for Account Deletion",
    responses={
        200: {"description": "Account deleted successfully", "model": DeleteVerifyResponse},
        401: {"description": "Invalid or expired token / wrong code", "model": ErrorResponse},
    },
)
async def verify_delete_email(
    request: VerifyDeleteRequest,
    temp_token: str = Header(..., alias="Temp-Token"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Complete account deletion by verifying the email verification code.
    """
    try:
        temp_token_hashed = hash_token(temp_token)
        result = await db.execute(
            select(TempToken).where(
                TempToken.token_hashed == temp_token_hashed,
                TempToken.token_type == TokenType.DELETE_ACCOUNT,
            )
        )
        token_record = result.scalar_one_or_none()

        if not token_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid or expired token"},
            )

        if datetime.now(timezone.utc) > token_record.expire_at:
            await db.delete(token_record)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid or expired token"},
            )

        # Verify email code
        if not token_record.verification_code_hashed or not verify_password(
            request.code, token_record.verification_code_hashed
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Wrong code or expired token"},
            )

        # Load user
        result = await db.execute(
            select(Account).where(Account.user_id == token_record.user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await db.delete(token_record)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid or expired token"},
            )

        # Delete all sessions from Redis
        if redis:
            await delete_all_user_sessions(redis, user.user_id)

        # Delete account (CASCADE handles all related data)
        await db.delete(token_record)
        await db.delete(user)
        await db.commit()

        logger.info(f"Account deleted via email verification for user_id={user.user_id}")
        return DeleteVerifyResponse(message="Account deleted successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete account email verify error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )

def _format_browser(ua) -> str:
    """Return '<family> <major>' or 'Unknown'."""
    family = ua.browser.family
    version = ua.browser.version_string
    if not family or family == "Other":
        return "Unknown"
    # Only include major version for readability
    major = version.split(".")[0] if version else ""
    return f"{family} {major}".strip()


def _format_os(ua) -> str:
    """Return '<os_family> <os_version>' or 'Unknown'."""
    family = ua.os.family
    version = ua.os.version_string
    if not family or family == "Other":
        return "Unknown"
    return f"{family} {version}".strip()


# ============ Logout Specific Device ============
@router.delete(
    "/settings/devices/{session_id}",
    response_model=LogoutDeviceResponse,
    status_code=status.HTTP_200_OK,
    summary="Logout Specific Device",
    responses={
        200: {"description": "Device session logged out successfully", "model": LogoutDeviceResponse},
        400: {"description": "Cannot logout current device", "model": ErrorResponse},
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        404: {"description": "Session not found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def logout_device(
    session_id: int,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Logout a specific device by session_id.

    The session_id can be obtained from GET /auth/settings/devices.
    Logging out the current device (is_current=true) is not allowed;
    use /auth/logout instead.

    - **session_id**: ID of the session to revoke (path parameter)
    - **Authorization**: Bearer token (refresh token) in header
    """
    try:
        user_id = await get_current_user_id(authorization, db, redis)

        # Hash the current token to identify the caller's own session
        current_token = authorization.replace("Bearer ", "")
        current_token_hashed = hash_token(current_token)

        # Look up the session, ensuring it belongs to the current user
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.id == session_id,
                RefreshToken.user_id == user_id,
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Session not found"},
            )

        # Prevent logging out the current device
        if session.token_hashed == current_token_hashed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Cannot logout current device, use /auth/logout instead"},
            )

        token_hashed = session.token_hashed

        # Clean Redis cache BEFORE committing the DB delete.
        # get_current_user_id trusts Redis on cache hit, so if we
        # committed the DB row first and Redis cleanup failed, the
        # revoked token would remain usable and the user couldn't retry.
        if redis:
            await delete_session_by_hash(redis, token_hashed, user_id)

        # Delete from DB (include user_id to prevent TOCTOU races)
        delete_result = await db.execute(
            delete(RefreshToken).where(
                RefreshToken.id == session_id,
                RefreshToken.user_id == user_id,
            )
        )
        if delete_result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Session not found"},
            )
        await db.commit()

        logger.info(f"Logout device session_id={session_id} for user_id={user_id}")

        return LogoutDeviceResponse(message="Device session has been logged out")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout device error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


# ============ Get Devices ============
@router.get(
    "/settings/devices",
    response_model=DevicesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get All Device Login Sessions",
    responses={
        200: {"description": "Successfully retrieved device list", "model": DevicesResponse},
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def get_devices(
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Returns all active login sessions for the current user.

    Each session includes parsed browser, OS, and device type information
    derived from the stored User-Agent string, as well as whether it is
    the session making the current request.

    - **Authorization**: Bearer token (refresh token) in header
    """
    try:
        user_id = await get_current_user_id(authorization, db, redis)

        # Extract current token hash for is_current comparison
        current_token = authorization.replace("Bearer ", "")
        current_token_hashed = hash_token(current_token)

        # Fetch all non-expired sessions for the user
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.expire_at > datetime.now(timezone.utc),
            )
        )
        sessions = result.scalars().all()

        devices = []
        for s in sessions:
            ua = parse_ua(s.user_agent or "")
            devices.append(DeviceSession(
                session_id=s.id,
                browser=_format_browser(ua),
                os=_format_os(ua),
                device_type=_parse_device_type(ua),
                created_at=s.created_at.isoformat() if s.created_at else "",
                is_current=(s.token_hashed == current_token_hashed),
            ))

        return DevicesResponse(devices=devices, total=len(devices))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get devices error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )

