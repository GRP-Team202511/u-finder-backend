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


# ============ All Profile ============
class ProfileSectionData(BaseModel):
    data: List[Dict[str, Any]]


class PersonalInfoData(BaseModel):
    name: str
    gender: str
    birthday: Optional[str] = None


class PersonalInfoUpdateData(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    gender: str = Field(..., min_length=1, max_length=20)
    birthday: str = Field(...)


class AllProfileResponse(BaseModel):
    personalInfo: PersonalInfoData
    education: ProfileSectionData
    academic: ProfileSectionData
    test: ProfileSectionData
    internship: ProfileSectionData
    project: ProfileSectionData
    campus: ProfileSectionData
    award: ProfileSectionData


class UpdateAllProfileRequest(BaseModel):
    personalInfo: PersonalInfoUpdateData
    education: ProfileSectionData
    academic: ProfileSectionData
    test: ProfileSectionData
    internship: ProfileSectionData
    project: ProfileSectionData
    campus: ProfileSectionData
    award: ProfileSectionData


class UpdateAllProfileResponse(BaseModel):
    message: str


# ============ Liked University (Program Card) ============

class UniversityInfo(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    country: Optional[str] = None
    city: Optional[str] = None
    official_website: str = Field(..., min_length=1)


class FacultyInfo(BaseModel):
    name: Optional[str] = None
    official_website: Optional[str] = None


class DegreeProgramInfo(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    degree_level: str = Field(..., min_length=1, max_length=100)
    field: str = Field(..., min_length=1, max_length=300)
    track_or_specialization: Optional[str] = None
    program_type: str = Field(..., min_length=1, max_length=100)
    duration: Optional[str] = None
    language: Optional[str] = None


class AdmissionsInfo(BaseModel):
    academic_requirements: Optional[str] = None
    language_requirements: Optional[str] = None
    other_requirements: Optional[str] = None
    application_deadline: Optional[str] = None


class TuitionInfo(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = None
    per: Optional[str] = None


class ProgramCardRequest(BaseModel):
    """LLM program card payload.programs — sent by frontend after SSE parsing."""
    university: UniversityInfo
    faculty: Optional[FacultyInfo] = None
    degree_program: DegreeProgramInfo
    admissions: Optional[AdmissionsInfo] = None
    tuition: Optional[TuitionInfo] = None
    career_outcomes: Optional[List[str]] = None
    official_program_url: str = Field(..., min_length=1)
    last_verified: Optional[str] = None


class CheckFavoriteResponse(BaseModel):
    unit_id: str
    is_liked: bool


class LikeResponse(BaseModel):
    unit_id: str
    is_liked: bool


class UnlikeResponse(BaseModel):
    unit_id: str
    is_liked: bool


class LikedUniversityItem(BaseModel):
    unit_id: str
    liked_at: str
    program: Dict[str, Any]


class LikedUniversityListResponse(BaseModel):
    data: List[LikedUniversityItem]


# ============ Common ============
class ErrorResponse(BaseModel):
    message: str
