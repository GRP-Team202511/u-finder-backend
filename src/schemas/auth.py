"""
Authentication related Pydantic models
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Literal, Optional
import re


# ============ Login ============
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    id: int
    name: str
    token: str


class Login2FARequiredResponse(BaseModel):
    temp_token: str


# ============ Logout ============
class LogoutResponse(BaseModel):
    message: str


class LogoutAllResponse(BaseModel):
    message: str
    revoked_count: int


# ============ Sign Up ============
class SignUpRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="User's display name")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=20, description="User's password (8-20 characters)")
    # Note: user_type is automatically set to 1 (user) by default
    
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


# ============ Delete Account ============
class DeleteAccountResponse(BaseModel):
    temp_token: str
    verification: Literal["2fa", "email"]


class VerifyDeleteRequest(BaseModel):
    code: str


class DeleteVerifyResponse(BaseModel):
    message: str


# ============ Update Username ============
class UpdateUsernameRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=20, description="New username (display name)")


class UpdateUsernameResponse(BaseModel):
    message: str


# ============ Get User Info ============
class GetUserInfoResponse(BaseModel):
    email: str
    name: str
    user_type: int


# ============ Get Devices ============
class DeviceSession(BaseModel):
    session_id: int
    browser: str
    os: str
    device_type: str
    created_at: str
    is_current: bool


class DevicesResponse(BaseModel):
    devices: list[DeviceSession]
    total: int


class LogoutDeviceResponse(BaseModel):
    message: str


# ============ Error Response ============
class ErrorResponse(BaseModel):
    message: str


