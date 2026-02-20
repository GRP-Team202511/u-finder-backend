"""
Authentication router module
Contains authentication related endpoints such as user login
"""
from fastapi import APIRouter, HTTPException, Header, status, Depends
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    SignUpRequest,
    SignUpResponse,
    VerifySignupEmailRequest,
    VerifySignupEmailResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    VerifyResetCodeRequest,
    VerifyResetCodeResponse,
    ResendResetCodeResponse,
    RateLimitResponse,
    ConfirmResetPasswordRequest,
    ConfirmResetPasswordResponse,
    UpdateUserTypeRequest,
    UpdateUserTypeResponse,
    GetUserInfoResponse,
    ErrorResponse,
)
from src.utils import (
    create_access_token,
    verify_token,
    create_temp_token,
    generate_verification_code,
    hash_password,
    verify_password,
    send_verification_email,
    get_token_data,
    verify_admin_from_db,
)
from src.config.logger import get_logger
from src.config.constants import UserType
from src.database import get_db, Account, UserProfile, TempToken, RefreshToken

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
    
    # Check if temp token exists with correct type
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token,
            TempToken.token_type == "password_reset"
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
        401: {"description": "Incorrect password", "model": ErrorResponse},
        404: {"description": "User not found", "model": ErrorResponse}
    }
)
async def login(
    login_data: LoginRequest,
    user_agent: str = Header(default="Unknown", alias="User-Agent"),
    db: AsyncSession = Depends(get_db)
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
        
        # Check if user exists
        if not user:
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
        
        # Create refresh token and store in database
        refresh_token = create_temp_token()
        refresh_token_record = RefreshToken(
            user_id=user.user_id,
            token_hashed=hash_password(refresh_token),
            user_agent=user_agent[:100],  # Limit to 100 chars
            expire_at=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db.add(refresh_token_record)
        await db.commit()
        
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
    db: AsyncSession = Depends(get_db)
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
        
        # Find and delete the refresh token
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hashed == hash_password(token))
        )
        refresh_token_record = result.scalar_one_or_none()
        
        if not refresh_token_record:
            logger.warning("Logout failed: Token not found")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid or expired token"}
            )
        
        # Delete the refresh token
        await db.delete(refresh_token_record)
        await db.commit()
        
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
    Administrators can change user type through admin panel.
    
    Returns temp_token for email verification
    """
    logger.info(f"Signup attempt for email: {request.email}")
    
    # Normalize email to lowercase
    email = request.email.lower()
    
    # Check if account already exists
    result = await db.execute(select(Account).where(Account.email == email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        logger.warning(f"Signup failed: Account already exists for email: {email}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Account exists"}
        )
    
    # Generate temp token and verification code
    temp_token = create_temp_token()
    verification_code = generate_verification_code()
    
    # Hash password
    password_hashed = hash_password(request.password)
    
    # Create temporary account (not yet verified)
    # Store in TempToken with additional data in a JSON field or create Account directly
    # For simplicity, create Account with is_blocked=True until verified
    # Default user_type=1 (student), administrators can modify through admin panel
    new_account = Account(
        user_name=request.name,
        email=email,
        password_hashed=password_hashed,
        user_type=1,  # Default: student user type (controlled by admin)
        is_blocked=True  # Block until email verified
    )
    
    db.add(new_account)
    await db.commit()
    await db.refresh(new_account)
    
    # Create temp token for email verification with hashed verification code
    temp_token_record = TempToken(
        user_id=new_account.user_id,
        token_hashed=temp_token,
        token_type="email_verify",
        verification_code_hashed=hash_password(verification_code),  # Hash the verification code
        expire_at=datetime.now(timezone.utc) + timedelta(hours=24)  # 24 hour expiry
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
    
    # Check if temp token exists with correct type
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token,
            TempToken.token_type == "email_verify"
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
        select(Account).where(Account.user_id == verification.user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        logger.error(f"Signup verification failed: User not found for user_id: {verification.user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found"}
        )
    
    # Unblock account (activate)
    user.is_blocked = False
    
    # Create user profile
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
        token_hashed=hash_password(refresh_token),
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
        token_hashed=temp_token,
        token_type="password_reset",
        verification_code_hashed=hash_password(reset_code),  # Hash the reset code
        expire_at=datetime.now(timezone.utc) + timedelta(hours=1)  # 1 hour expiry
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
    
    # Check if temp token exists with correct type
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token,
            TempToken.token_type == "password_reset"
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
    "/resend-reset-code",
    response_model=ResendResetCodeResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Token expired or invalid"},
        404: {"model": ErrorResponse, "description": "User not found"},
        429: {"model": RateLimitResponse, "description": "Too many requests"},
    },
)
async def resend_reset_code(
    temp_token: str = Header(..., alias="temp-token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Resend password reset verification code

    - **temp-token**: Temporary token from reset-password endpoint (in header)

    Returns success message if code is resent successfully.
    """
    logger.info("Resend reset code attempt with temp-token")

    # Check if temp token exists with correct type
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token,
            TempToken.token_type == "password_reset",
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found"},
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


# ============ Admin - Update User Type ============
@router.put(
    "/admin/users/{user_id}/type",
    response_model=UpdateUserTypeResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin: Update User Type",
    include_in_schema=False,
    responses={
        200: {"description": "User type updated successfully", "model": UpdateUserTypeResponse},
        403: {"description": "Admin privileges required", "model": ErrorResponse},
        404: {"description": "User not found", "model": ErrorResponse}
    }
)
async def update_user_type(
    user_id: int,
    request: UpdateUserTypeRequest,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a user's type (admin only)
    
    **Requires**: Admin authentication (user_type = 99)
    
    - **user_id**: ID of the user to update
    - **user_type**: New user type value
      - 1 = Student
      - 2 = Institution
      - 99 = Administrator
    
    Returns updated user information
    """
    try:
        # Verify admin privileges
        token_data = get_token_data(authorization)
        admin = await verify_admin_from_db(token_data["user_id"], db)
        
        logger.info(f"Admin {admin.user_id} attempting to update user_type for user {user_id}")
        
        # Query target user
        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        target_user = result.scalar_one_or_none()
        
        if not target_user:
            logger.warning(f"Update user type failed: User {user_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "User not found"}
            )
        
        # Update user type
        old_type = target_user.user_type
        target_user.user_type = request.user_type
        await db.commit()
        
        logger.info(
            f"User type updated: user_id={user_id}, "
            f"old_type={old_type}, new_type={request.user_type}, "
            f"admin={admin.user_id}"
        )
        
        return UpdateUserTypeResponse(
            user_id=user_id,
            user_type=request.user_type,
            message=f"User type updated to {UserType.get_description(request.user_type)}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update user type error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"}
        )


# ============ Admin - Get User Info ============
@router.get(
    "/admin/users/{user_id}",
    response_model=GetUserInfoResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin: Get User Information",
    include_in_schema=False,
    responses={
        200: {"description": "User information retrieved", "model": GetUserInfoResponse},
        403: {"description": "Admin privileges required", "model": ErrorResponse},
        404: {"description": "User not found", "model": ErrorResponse}
    }
)
async def get_user_info(
    user_id: int,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed user information (admin only)
    
    **Requires**: Admin authentication (user_type = 99)
    
    - **user_id**: ID of the user to query
    
    Returns detailed user account information
    """
    try:
        # Verify admin privileges
        token_data = get_token_data(authorization)
        admin = await verify_admin_from_db(token_data["user_id"], db)
        
        logger.info(f"Admin {admin.user_id} querying info for user {user_id}")
        
        # Query target user
        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            logger.warning(f"Get user info failed: User {user_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "User not found"}
            )
        
        return GetUserInfoResponse(
            user_id=user.user_id,
            email=user.email,
            user_type=user.user_type,
            user_type_description=UserType.get_description(user.user_type),
            is_blocked=user.is_blocked,
            is_2fa_enabled=user.is_2fa_enabled,
            passkey_enabled=user.passkey_enabled,
            created_at=user.created_at.isoformat(),
            updated_at=user.updated_at.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user info error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"}
        )

