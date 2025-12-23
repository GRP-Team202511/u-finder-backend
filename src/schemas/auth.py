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


# ============ Sign Up ============
class SignUpRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="User's full name")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128, description="User's password (8-128 characters)")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate name is not just whitespace"""
        if not v or not v.strip():
            raise ValueError('Name cannot be empty or just whitespace')
        return v.strip()
    
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
    token: str  # temp_token for email verification


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


class ConfirmResetPasswordRequest(BaseModel):
    code: str
    new_password: str = Field(..., min_length=8, max_length=128, description="New password (8-128 characters)")
    
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


class ConfirmResetPasswordResponse(BaseModel):
    message: str


# ============ Error Response ============
class ErrorResponse(BaseModel):
    message: str
