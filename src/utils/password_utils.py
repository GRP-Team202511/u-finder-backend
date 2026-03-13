"""
Password utility functions
Handle password hashing and verification
"""
import hashlib
import hmac
import bcrypt

from src.config.settings import get_settings


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against

    Returns:
        True if password matches, False otherwise
    """
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def hash_token(token: str) -> str:
    """
    Produce a deterministic HMAC-SHA256 hex digest of a token.

    Unlike bcrypt, this is fast and always returns the same output for the
    same input, making it suitable for exact-match database lookups.
    Tokens (refresh tokens, temp tokens) are already high-entropy random
    values, so the slow salting properties of bcrypt are unnecessary.

    Args:
        token: Plain-text token string

    Returns:
        64-character lowercase hex string
    """
    secret = get_settings().secret_key.encode()
    return hmac.new(secret, token.encode(), hashlib.sha256).hexdigest()
