"""
Profile router module
Contains endpoints for user profile management
"""
import json
from fastapi import APIRouter, HTTPException, Header, status, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from redis.asyncio import Redis
from typing import Optional, Any

from src.schemas.profile import (
    PersonalInfoResponse,
    UpdatePersonalInfoRequest,
    UpdatePersonalInfoResponse,
    ArrayProfileResponse,
    UpdateArrayProfileRequest,
    UpdateArrayProfileResponse,
    AllProfileResponse,
    UpdateAllProfileRequest,
    UpdateAllProfileResponse,
    ProfileSectionData,
    PersonalInfoData,
    ErrorResponse,
    VALID_ARRAY_FIELDS,
    FIELD_DISPLAY_NAMES,
)
from src.config.logger import get_logger
from src.config.settings import get_settings
from src.database import get_db, get_redis, Account, UserProfile, RefreshToken
from src.utils.session_utils import get_session
from src.utils.password_utils import hash_token
from src.services.dify_service import (
    upload_file_to_dify,
    run_cv_parsing_workflow,
    DifyUpstreamError,
)

logger = get_logger(__name__)
settings = get_settings()

ALLOWED_CV_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

router = APIRouter(prefix="/profile", tags=["Profile"])


async def _get_current_user_id(
    authorization: str,
    db: AsyncSession,
    redis: Optional[Redis],
) -> int:
    """
    Extract and verify the refresh token from Authorization header.
    Returns the user_id associated with the session.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        )

    token = authorization.replace("Bearer ", "")

    # 1. Try Redis cache first
    if redis is not None:
        session_data = await get_session(redis, token)
        if session_data:
            return int(session_data["user_id"])

    # 2. Fallback to database
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hashed == hash_token(token)
        )
    )
    refresh_record = result.scalar_one_or_none()

    if not refresh_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        )

    return refresh_record.user_id


def _safe_array_data(value: Any) -> list[dict]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("data"), list):
        return value["data"]
    return []


def _parse_dify_section(outputs: dict, key: str) -> list:
    """
    Safely parse a profile section from Dify workflow outputs.

    Dify may return the section as:
      - a list of dicts
      - a dict with a "data" key containing a list
      - a JSON string that needs decoding
      - None / missing
    """
    raw = outputs.get(key)
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        return raw["data"]
    return []


def _parse_dify_personal_info(outputs: dict) -> dict:
    """
    Safely parse personalInfo from Dify workflow outputs.

    May be a dict or a JSON string.
    """
    raw = outputs.get("personalInfo")
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


# ──────────────────────────────────────────────
# CV Upload & Parsing
# ──────────────────────────────────────────────

@router.post(
    "/cv",
    response_model=AllProfileResponse,
    responses={
        400: {"description": "No file uploaded or file is empty", "model": ErrorResponse},
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        413: {"description": "File too large", "model": ErrorResponse},
        415: {"description": "Unsupported file type", "model": ErrorResponse},
        422: {"description": "Failed to extract information", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
        502: {"description": "AI service unavailable", "model": ErrorResponse},
    },
    summary="CV Upload",
    description=(
        "Upload a CV file (PDF or DOCX). The server forwards it to the Dify AI "
        "service for information extraction and returns the structured result."
    ),
)
async def upload_cv(
    file: UploadFile = File(None),
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        # ── Auth ──
        user_id = await _get_current_user_id(authorization, db, redis)

        # ── Validate file presence ──
        if file is None or file.filename is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "No file uploaded"},
            )

        # ── Validate content type ──
        if file.content_type not in ALLOWED_CV_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail={"message": "Unsupported file type. Only PDF and DOCX are allowed"},
            )

        # ── Read and validate size ──
        file_content = await file.read()

        if len(file_content) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Uploaded file is empty"},
            )

        if len(file_content) > settings.cv_max_file_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"message": "File too large. Maximum size is 10 MB"},
            )

        # ── Upload file to Dify ──
        upload_file_id = await upload_file_to_dify(
            file_content=file_content,
            filename=file.filename,
            content_type=file.content_type,
            user=str(user_id),
        )

        # ── Run Dify workflow ──
        outputs = await run_cv_parsing_workflow(
            upload_file_id=upload_file_id,
            filename=file.filename,
            user=str(user_id),
        )

        # ── Parse structured output ──
        personal = _parse_dify_personal_info(outputs)

        response = AllProfileResponse(
            personalInfo=PersonalInfoData(
                name=personal.get("name", ""),
                gender=personal.get("gender", ""),
                birthday=personal.get("birthday", ""),
            ),
            education=ProfileSectionData(data=_parse_dify_section(outputs, "education")),
            academic=ProfileSectionData(data=_parse_dify_section(outputs, "academic")),
            test=ProfileSectionData(data=_parse_dify_section(outputs, "test")),
            internship=ProfileSectionData(data=_parse_dify_section(outputs, "internship")),
            project=ProfileSectionData(data=_parse_dify_section(outputs, "project")),
            campus=ProfileSectionData(data=_parse_dify_section(outputs, "campus")),
            award=ProfileSectionData(data=_parse_dify_section(outputs, "award")),
        )

        logger.info("CV parsed successfully for user %d", user_id)
        return response

    except HTTPException:
        raise
    except DifyUpstreamError as e:
        logger.error("Dify error during CV parsing: status=%d", e.status_code)
        if e.status_code == 422:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "Failed to extract information from the uploaded file"},
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "AI service is temporarily unavailable. Please try again later"},
        )
    except Exception as e:
        logger.error("CV upload error: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


@router.get(
    "",
    response_model=AllProfileResponse,
    responses={
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        404: {"description": "Profile not found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get All Profile",
    description="Return all user's profile",
)
async def get_all_profile(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        result = await db.execute(select(Account).where(Account.user_id == user_id))
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Profile not found"},
            )

        result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        basic_info = (profile.basic_info or {}) if profile else {}

        return AllProfileResponse(
            personalInfo=PersonalInfoData(
                name=basic_info.get("name") or account.user_name,
                gender=basic_info.get("gender") or "",
                birthday=basic_info.get("birthday") or "",
            ),
            education=ProfileSectionData(data=_safe_array_data(profile.education if profile else None)),
            academic=ProfileSectionData(data=_safe_array_data(profile.academic if profile else None)),
            test=ProfileSectionData(data=_safe_array_data(profile.test if profile else None)),
            internship=ProfileSectionData(data=_safe_array_data(profile.internship if profile else None)),
            project=ProfileSectionData(data=_safe_array_data(profile.project if profile else None)),
            campus=ProfileSectionData(data=_safe_array_data(profile.campus if profile else None)),
            award=ProfileSectionData(data=_safe_array_data(profile.award if profile else None)),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get all profile error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


@router.put(
    "",
    response_model=UpdateAllProfileResponse,
    responses={
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        404: {"description": "Profile data not found", "model": ErrorResponse},
        422: {"description": "Validation error", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Update All Profile",
    description="Update all user profile data including personal info and all profile sections",
)
async def update_all_profile(
    request: UpdateAllProfileRequest,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        result = await db.execute(select(Account).where(Account.user_id == user_id))
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Profile data not found"},
            )

        result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if not profile:
            profile = UserProfile(user_id=user_id)
            db.add(profile)

        existing_basic_info = profile.basic_info or {}
        existing_basic_info.update({
            "name": request.personalInfo.name,
            "gender": request.personalInfo.gender,
            "birthday": request.personalInfo.birthday,
        })
        profile.basic_info = existing_basic_info
        profile.education = request.education.data
        profile.academic = request.academic.data
        profile.test = request.test.data
        profile.internship = request.internship.data
        profile.project = request.project.data
        profile.campus = request.campus.data
        profile.award = request.award.data

        account.user_name = request.personalInfo.name

        await db.commit()
        logger.info(f"All profile updated for user {user_id}")
        return UpdateAllProfileResponse(message="All profiles updated successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update all profile error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


@router.get(
    "/personal",
    response_model=PersonalInfoResponse,
    responses={
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        404: {"description": "User not found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get Personal Info",
)
async def get_personal_info(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Get the authenticated user's personal info (name, gender, birthday).

    **Requires**: Bearer token (refresh token) in Authorization header.
    """
    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        # Fetch account
        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        account = result.scalar_one_or_none()

        if not account:
            logger.warning(f"Get personal info failed: user {user_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "User not found"},
            )

        # Fetch profile
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        basic_info = (profile.basic_info or {}) if profile else {}

        return PersonalInfoResponse(
            name=basic_info.get("name", account.user_name),
            gender=basic_info.get("gender", ""),
            birthday=basic_info.get("birthday"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get personal info error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


@router.put(
    "/personal",
    response_model=UpdatePersonalInfoResponse,
    responses={
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        404: {"description": "User not found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Update Personal Info",
    description="Update personal info",
)
async def update_personal_info(
    request: UpdatePersonalInfoRequest,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Update the authenticated user's personal info (name, gender, birthday).

    **Requires**: Bearer token (refresh token) in Authorization header.
    """
    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        # Fetch account
        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        account = result.scalar_one_or_none()

        if not account:
            logger.warning(f"Update personal info failed: user {user_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "User not found"},
            )

        # Fetch or create profile
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        new_basic_info = {
            "name": request.name,
            "gender": request.gender,
            "birthday": request.birthday,
        }

        if profile:
            # Merge with existing basic_info to preserve other fields if any
            existing = profile.basic_info or {}
            existing.update(new_basic_info)
            profile.basic_info = existing
        else:
            profile = UserProfile(user_id=user_id, basic_info=new_basic_info)
            db.add(profile)

        # Also sync display name on account table
        account.user_name = request.name

        await db.commit()
        logger.info(f"Personal info updated for user {user_id}")

        return UpdatePersonalInfoResponse(message="Update successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update personal info error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


@router.get(
    "/array/{field}",
    response_model=ArrayProfileResponse,
    responses={
        400: {"description": "Invalid field", "model": ErrorResponse},
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        404: {"description": "Profile data not found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get Other Profile",
)
async def get_array_profile(
    field: str,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Get the authenticated user's array-type profile data for the specified field.

    **Requires**: Bearer token (refresh token) in Authorization header.

    **Field** must be one of: education, academic, test, internship, project, campus, award
    """
    # Validate field
    if field not in VALID_ARRAY_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": f"Invalid field. Must be one of: {', '.join(sorted(VALID_ARRAY_FIELDS))}"},
        )

    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        # Fetch profile
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Profile data not found"},
            )

        field_data = getattr(profile, field, None)
        if field_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Profile data not found"},
            )

        return ArrayProfileResponse(data=field_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get array profile ({field}) error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


@router.put(
    "/array/{field}",
    response_model=UpdateArrayProfileResponse,
    responses={
        400: {"description": "Invalid field", "model": ErrorResponse},
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        404: {"description": "User profile not found", "model": ErrorResponse},
        422: {"description": "Validation error", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Update Other Profile",
)
async def update_array_profile(
    field: str,
    request: UpdateArrayProfileRequest,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """
    Update the authenticated user's array-type profile data for the specified field.

    **Requires**: Bearer token (refresh token) in Authorization header.

    **Field** must be one of: education, academic, test, internship, project, campus, award
    """
    # Validate field
    if field not in VALID_ARRAY_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": f"Invalid field. Must be one of: {', '.join(sorted(VALID_ARRAY_FIELDS))}"},
        )

    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        # Fetch or create profile
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        if not profile:
            profile = UserProfile(user_id=user_id)
            db.add(profile)

        setattr(profile, field, request.data)

        await db.commit()
        display_name = FIELD_DISPLAY_NAMES.get(field, field.capitalize())
        logger.info(f"{display_name} updated for user {user_id}")

        return UpdateArrayProfileResponse(message=f"{display_name} saved successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update array profile ({field}) error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )
