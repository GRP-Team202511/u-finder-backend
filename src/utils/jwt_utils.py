"""
JWT utility functions
Handles JWT token generation and verification
"""
import jwt
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from src.config.settings import get_settings

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
