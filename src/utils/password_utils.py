"""
Password utility functions
Handle password hashing and verification
"""
import bcrypt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify if plain password matches the hashed password
    
    Args:
        plain_password: Plain text password
        hashed_password: Hashed password
    
    Returns:
        True if matched, False otherwise
    """
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def get_password_hash(password: str) -> str:
    """
    Hash a password
    
    Args:
        password: Plain text password
    
    Returns:
        Hashed password string
    """
    # Generate salt and hash password
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')
