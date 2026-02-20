"""
JWT utility functions
Handles JWT token generation and verification
"""
import jwt
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from fastapi import HTTPException, Header, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.config.settings import get_settings
from src.config.constants import UserType

# Get settings
settings = get_settings()

# JWT Configuration from settings
SECRET_KEY = settings.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token
    
    Args:
        data: Payload data to encode in the token
        expires_delta: Optional custom expiration time
    
    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """
    Verify and decode a JWT token
    
    Args:
        token: JWT token string to verify
    
    Returns:
        Decoded payload if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def create_temp_token() -> str:
    """
    Create a temporary token for email verification or password reset
    
    Returns:
        Random secure token string
    """
    return secrets.token_urlsafe(32)


def generate_verification_code(length: int = 6) -> str:
    """
    Generate a numeric verification code
    
    Args:
        length: Length of the verification code
    
    Returns:
        Numeric verification code string
    """
    return ''.join([str(secrets.randbelow(10)) for _ in range(length)])


def get_token_data(authorization: str = Header(...)) -> Dict:
    """
    Extract and verify JWT token from Authorization header
    
    Args:
        authorization: Authorization header (Bearer token)
    
    Returns:
        Dict with user_id, email, and user_type from token
    
    Raises:
        HTTPException: If token is invalid or expired
    """
    # Extract token from Authorization header
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid authorization header format"}
        )
    
    token = authorization.replace("Bearer ", "")
    
    # Verify token
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"}
        )
    
    # Get user_id from payload
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid token payload"}
        )
    
    return {
        "user_id": int(user_id),
        "email": payload.get("email"),
        "user_type": payload.get("user_type")
    }


async def verify_user_from_db(user_id: int, db: AsyncSession):
    """
    Verify user exists and is not blocked
    
    Args:
        user_id: User ID
        db: Database session
    
    Returns:
        Account object
    
    Raises:
        HTTPException: If user not found or blocked
    """
    from src.database import Account
    
    result = await db.execute(
        select(Account).where(Account.user_id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found"}
        )
    
    if user.is_blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Account is blocked"}
        )
    
    return user


async def verify_refresh_token_from_db(token: str, db: AsyncSession):
    """
    Verify refresh token exists in database and is not expired
    
    Args:
        token: Refresh token string
        db: Database session
    
    Returns:
        Tuple of (Account object, RefreshToken object)
    
    Raises:
        HTTPException: If token invalid, expired, or user blocked
    """
    from src.database import Account, RefreshToken
    from src.utils.password_utils import verify_password
    from datetime import datetime, timezone
    
    # Find refresh token in database
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hashed == token)
    )
    refresh_token_record = result.scalar_one_or_none()
    
    if not refresh_token_record:
        # Try to verify against hashed token
        result = await db.execute(select(RefreshToken))
        all_tokens = result.scalars().all()
        
        refresh_token_record = None
        for rt in all_tokens:
            if verify_password(token, rt.token_hashed):
                refresh_token_record = rt
                break
        
        if not refresh_token_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid or expired token"}
            )
    
    # Check if expired
    if datetime.now(timezone.utc) > refresh_token_record.expire_at:
        await db.delete(refresh_token_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"}
        )
    
    # Get user account
    result = await db.execute(
        select(Account).where(Account.user_id == refresh_token_record.user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found"}
        )
    
    if user.is_blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Account is blocked"}
        )
    
    return user, refresh_token_record


async def verify_admin_from_db(user_id: int, db: AsyncSession):
    """
    Verify user is admin
    
    Args:
        user_id: User ID
        db: Database session
    
    Returns:
        Account object of admin user
    
    Raises:
        HTTPException: If user not admin
    """
    user = await verify_user_from_db(user_id, db)
    
    if user.user_type != UserType.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Admin privileges required"}
        )
    
    return user
