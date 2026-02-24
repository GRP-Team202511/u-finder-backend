"""
Authentication related Pydantic models
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
import re


# ============ Login ============
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    id: int
    name: str
    token: str


# ============ Logout ============
class LogoutResponse(BaseModel):
    message: str


# ============ Sign Up ============
class SignUpRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="User's display name")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128, description="User's password (8-128 characters)")
    # Note: user_type is automatically set to 1 (student) by default
    # Administrators can change user type through admin panel
    
    @field_validator('email')
    @classmethod
    def validate_email_lowercase(cls, v: str) -> str:
        """Ensure email is lowercase"""
        return v.lower()
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password strength"""
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Za-z]', v):
            raise ValueError('Password must contain at least one letter')
        if not re.search(r'[0-9]', v):
            raise ValueError('Password must contain at least one number')
        return v


class SignUpResponse(BaseModel):
    temp_token: str  # Temporary token for email verification


# ============ Verify Signup Email ============
class VerifySignupEmailRequest(BaseModel):
    code: str


class VerifySignupEmailResponse(BaseModel):
    id: int
    name: str
    token: str  # JWT token


# ============ Reset Password ============
class ResetPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordResponse(BaseModel):
    temp_token: str


class VerifyResetCodeRequest(BaseModel):
    code: str


class VerifyResetCodeResponse(BaseModel):
    message: str


class ResendSignupCodeResponse(BaseModel):
    message: str


class ResendResetCodeResponse(BaseModel):
    message: str


class RateLimitResponse(BaseModel):
    message: str
    retryAfter: int


class ConfirmResetPasswordRequest(BaseModel):
    code: str
    new_password: str = Field(
        ..., min_length=8, max_length=128, description="New password (8-128 characters)", alias="newPassword"
    )
    
    @field_validator('new_password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password strength"""
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Za-z]', v):
            raise ValueError('Password must contain at least one letter')
        if not re.search(r'[0-9]', v):
            raise ValueError('Password must contain at least one number')
        return v

    model_config = {
        "populate_by_name": True
    }


class ConfirmResetPasswordResponse(BaseModel):
    message: str


# ============ Error Response ============
class ErrorResponse(BaseModel):
    message: str


# ============ Admin - Update User Type ============
class UpdateUserTypeRequest(BaseModel):
    user_type: int = Field(..., description="New user type (1=student, 2=institution, 99=admin)")
    
    @field_validator('user_type')
    @classmethod
    def validate_user_type(cls, v: int) -> int:
        """Validate user type value"""
        from src.config.constants import UserType
        if not UserType.is_valid(v):
            raise ValueError(f'Invalid user type. Must be one of: {UserType.STUDENT}, {UserType.INSTITUTION}, {UserType.ADMIN}')
        return v


class UpdateUserTypeResponse(BaseModel):
    user_id: int
    user_type: int
    message: str


class GetUserInfoResponse(BaseModel):
    user_id: int
    email: str
    user_type: int
    user_type_description: str
    is_blocked: bool
    is_2fa_enabled: bool
    passkey_enabled: bool
    created_at: str
    updated_at: str

