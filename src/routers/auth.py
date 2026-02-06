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
    SignUpRequest,
    SignUpResponse,
    VerifySignupEmailRequest,
    VerifySignupEmailResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    VerifyResetCodeRequest,
    VerifyResetCodeResponse,
    ConfirmResetPasswordRequest,
    ConfirmResetPasswordResponse,
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
)
from src.config.logger import get_logger
from src.database import get_db, User, SignUpVerification, PasswordReset

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
    
    # Check if temp token exists
    result = await db.execute(
        select(PasswordReset).where(PasswordReset.temp_token == temp_token)
    )
    reset_record = result.scalar_one_or_none()
    
    if not reset_record:
        logger.warning("Password reset failed: Invalid temp token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Check if expired
    if datetime.now(timezone.utc) > reset_record.expires_at:
        logger.warning("Password reset failed: Expired token")
        await db.delete(reset_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Verify code
    if request.code != reset_record.reset_code:
        logger.warning("Password reset failed: Wrong reset code")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Find user and update password
    result = await db.execute(select(User).where(User.email == reset_record.email))
    user = result.scalar_one_or_none()
    
    if not user:
        logger.error(f"Password reset failed: User not found for email: {reset_record.email}")
        await db.delete(reset_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found"}
        )
    
    # Update password
    user.password_hash = hash_password(request.new_password)
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
    db: AsyncSession = Depends(get_db)
):
    """
    User login endpoint
    
    - **email**: User email address (required)
    - **password**: User password (required)
    """
    try:
        logger.info(f"Login attempt for email: {login_data.email}")
        
        # Query user by email
        result = await db.execute(
            select(User).where(User.email == login_data.email)
        )
        user = result.scalar_one_or_none()
        
        # Check if user exists
        if not user:
            logger.warning(f"User not found: {login_data.email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "User not found"}
            )
        
        # Verify password
        if not verify_password(login_data.password, user.password_hash):
            logger.warning(f"Incorrect password for user: {login_data.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Incorrect password"}
            )
        
        # Create access token
        access_token = create_access_token(
            data={"sub": str(user.id), "email": user.email}
        )
        
        logger.info(f"Login successful for user: {login_data.email}")
        
        return LoginResponse(
            id=user.id,
            name=user.name,
            token=access_token
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
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
    
    - **name**: User's full name
    - **email**: User's email address
    - **password**: User's password
    
    Returns temp_token for email verification
    """
    logger.info(f"Signup attempt for email: {request.email}")
    
    # Check if account already exists
    result = await db.execute(select(User).where(User.email == request.email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        logger.warning(f"Signup failed: Account already exists for email: {request.email}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Account exists"}
        )
    
    # Generate temp token and verification code
    temp_token = create_temp_token()
    verification_code = generate_verification_code()
    
    # Hash password
    password_hash = hash_password(request.password)
    
    # Create signup verification record
    verification = SignUpVerification(
        temp_token=temp_token,
        name=request.name,
        email=request.email,
        password_hash=password_hash,
        verification_code=verification_code,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24)  # 24 hour expiry
    )
    
    db.add(verification)
    await db.commit()
    
    # Send verification code via email
    logger.info(f"Signup temp token created for email: {request.email}")
    email_sent = await send_verification_email(
        to_email=request.email,
        verification_code=verification_code,
        name=request.name,
        email_type="signup"
    )
    
    if not email_sent:
        logger.warning(f"Failed to send verification email to {request.email}, but signup record created")
    
    return SignUpResponse(token=temp_token)


# ============ Verify Signup Email ============
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
    temp_token: str = Header(..., alias="temp_token"),
    db: AsyncSession = Depends(get_db)
):
    """
    Signup email verification endpoint
    
    - **temp_token**: Temporary token from signup (in header)
    - **code**: Verification code sent to email
    
    Returns JWT token on successful verification and creates the user account
    """
    logger.info(f"Signup email verification attempt with temp_token")
    
    # Check if temp token exists
    result = await db.execute(
        select(SignUpVerification).where(SignUpVerification.temp_token == temp_token)
    )
    verification = result.scalar_one_or_none()
    
    if not verification:
        logger.warning("Signup email verification failed: Invalid temp token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code"}
        )
    
    # Check if expired
    if datetime.now(timezone.utc) > verification.expires_at:
        logger.warning("Signup email verification failed: Expired token")
        await db.delete(verification)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code"}
        )
    
    # Verify code
    if request.code != verification.verification_code:
        logger.warning("Signup email verification failed: Wrong verification code")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code"}
        )
    
    # Create user account
    new_user = User(
        name=verification.name,
        email=verification.email,
        password_hash=verification.password_hash,
        is_verified=True
    )
    
    db.add(new_user)
    await db.delete(verification)
    await db.commit()
    await db.refresh(new_user)
    
    # Generate JWT token
    token = create_access_token(data={"sub": str(new_user.id), "email": new_user.email})
    
    logger.info(f"Signup email verified and user created with ID: {new_user.id}")
    
    return VerifySignupEmailResponse(
        id=new_user.id,
        name=new_user.name,
        token=token
    )


# ============ Reset Password ============
@router.post(
    "/reset-password",
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
    
    # Check if user exists
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"Password reset failed: No account for email: {request.email}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "No account record for this email"}
        )
    
    # Generate temp token and reset code
    temp_token = create_temp_token()
    reset_code = generate_verification_code()
    
    # Create password reset record
    reset_record = PasswordReset(
        temp_token=temp_token,
        email=request.email,
        reset_code=reset_code,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)  # 1 hour expiry
    )
    
    db.add(reset_record)
    await db.commit()
    
    # Send reset code via email
    logger.info(f"Password reset temp token created for email: {request.email}")
    email_sent = await send_verification_email(
        to_email=request.email,
        verification_code=reset_code,
        name=user.name,
        email_type="reset"
    )
    
    if not email_sent:
        logger.warning(f"Failed to send reset code email to {request.email}, but reset record created")
    
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
    
    # Check if temp token exists
    result = await db.execute(
        select(PasswordReset).where(PasswordReset.temp_token == temp_token)
    )
    reset_record = result.scalar_one_or_none()
    
    if not reset_record:
        logger.warning("Reset code verification failed: Invalid temp token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Check if expired
    if datetime.now(timezone.utc) > reset_record.expires_at:
        logger.warning("Reset code verification failed: Expired token")
        await db.delete(reset_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Verify code
    if request.code != reset_record.reset_code:
        logger.warning("Reset code verification failed: Wrong reset code")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    logger.info(f"Reset code verified successfully for email: {reset_record.email}")
    
    return VerifyResetCodeResponse(message="Code verified successfully")


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
    temp_token: str = Header(..., alias="temp_token"),
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
