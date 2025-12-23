"""Models module - placeholder for backwards compatibility

All models have been moved to src.database.models
Import from src.database instead:
    from src.database import User, SignUpVerification, PasswordReset
"""
from src.database import User, SignUpVerification, PasswordReset

__all__ = ['User', 'SignUpVerification', 'PasswordReset']
