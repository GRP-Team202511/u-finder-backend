"""Models module - placeholder for backwards compatibility

All models have been moved to src.database.models
Import from src.database instead:
    from src.database import Account, UserProfile, TempToken, etc.
"""
from src.database import Account, UserProfile, RefreshToken, TotpBackupCode, Passkey, TempToken

__all__ = ['Account', 'UserProfile', 'RefreshToken', 'TotpBackupCode', 'Passkey', 'TempToken']
