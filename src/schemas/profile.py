"""
Profile related Pydantic models
"""
from pydantic import BaseModel, Field
from typing import Optional


# ============ Personal Info ============
class PersonalInfoResponse(BaseModel):
    name: str
    gender: str
    birthday: Optional[str] = None


class UpdatePersonalInfoRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    gender: str = Field(..., min_length=1, max_length=20)
    birthday: str = Field(...)


class UpdatePersonalInfoResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    message: str
