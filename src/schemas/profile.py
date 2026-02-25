"""
Profile related Pydantic models
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


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


# ============ Array Profile Fields ============
VALID_ARRAY_FIELDS = {"education", "academic", "test", "internship", "project", "campus", "award"}

FIELD_DISPLAY_NAMES = {
    "education": "Education Info",
    "academic": "Academic Info",
    "test": "Standardized Test Info",
    "internship": "Internship Info",
    "project": "Project Info",
    "campus": "Campus Experience Info",
    "award": "Award Info",
}


class ArrayProfileResponse(BaseModel):
    data: List[Dict[str, Any]]


class UpdateArrayProfileRequest(BaseModel):
    data: List[Dict[str, Any]] = Field(..., description="Array of profile data objects")


class UpdateArrayProfileResponse(BaseModel):
    message: str


# ============ Common ============
class ErrorResponse(BaseModel):
    message: str
