"""
Authentication related Pydantic models
"""
from pydantic import BaseModel, EmailStr
from typing import Optional


# =========== Login ===========
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    id: int
    name: str
    token: str


# =========== Sign Up ===========
class SignUpRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class SignUpResponse(BaseModel):
    token: str  # temp_token for email verification


# =========== Error ===========
class ErrorResponse(BaseModel):
    message: str
