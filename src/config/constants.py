# This code was completed by GRP Team 2025.11.
"""
Application constants and enumerations
"""
from enum import IntEnum


class UserType(IntEnum):
    """
    User type enumeration
    Defines different user roles in the system
    """
    USER = 1            # Regular user
    PRO_USER = 2        # Pro plan subscriber
    ADMIN = 3           # System administrator
    SUPER_ADMIN = 4     # Super administrator

    STUDENT = 1         # Alias (deprecated) — use USER instead
    INSTITUTION = 2     # Alias (deprecated) — use PRO_USER instead

    @classmethod
    def get_description(cls, value: int) -> str:
        """Get human-readable description of user type"""
        descriptions = {
            cls.USER: "User",
            cls.PRO_USER: "Pro User",
            cls.ADMIN: "Admin",
            cls.SUPER_ADMIN: "Super Admin",
        }
        return descriptions.get(value, "Unknown")

    @classmethod
    def is_valid(cls, value: int) -> bool:
        """Check if a user type value is valid"""
        return value in [cls.USER, cls.PRO_USER, cls.ADMIN, cls.SUPER_ADMIN]

    @classmethod
    def is_admin_level(cls, value: int) -> bool:
        """Check if a user type has admin-level access"""
        return value in [cls.ADMIN, cls.SUPER_ADMIN]

    @classmethod
    def assignable_roles(cls) -> list[int]:
        """Roles that can be assigned via the change-role API (excludes SUPER_ADMIN)"""
        return [cls.USER, cls.PRO_USER, cls.ADMIN]


class TokenType:
    """
    Token type constants for TempToken table
    """
    EMAIL_VERIFY = "email_verify"
    PASSWORD_RESET = "password_reset"
    EMAIL_CHANGE = "email_change"
    TWO_FACTOR_VERIFY = "2fa_verify"
    DELETE_ACCOUNT = "delete_account"
