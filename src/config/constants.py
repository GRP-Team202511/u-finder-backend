"""
Application constants and enumerations
"""
from enum import IntEnum


class UserType(IntEnum):
    """
    User type enumeration
    Defines different user roles in the system
    """
    STUDENT = 1         # Regular student user
    INSTITUTION = 2     # Educational institution account
    
    @classmethod
    def get_description(cls, value: int) -> str:
        """Get human-readable description of user type"""
        descriptions = {
            cls.STUDENT: "Student",
            cls.INSTITUTION: "Institution"
        }
        return descriptions.get(value, "Unknown")
    
    @classmethod
    def is_valid(cls, value: int) -> bool:
        """Check if a user type value is valid"""
        return value in [cls.STUDENT, cls.INSTITUTION]


class TokenType:
    """
    Token type constants for TempToken table
    """
    EMAIL_VERIFY = "email_verify"
    PASSWORD_RESET = "password_reset"
    EMAIL_CHANGE = "email_change"
