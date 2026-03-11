"""
Profile router module
Contains endpoints for user profile management
"""
import json
from pathlib import Path

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
    ProgramCardRequest,
    CheckFavoriteResponse,
    LikeResponse,
    UnlikeResponse,
    LikedUniversityItem,
    LikedUniversityListResponse,
    GetAvatarResponse,
    AvatarUploadResponse,
    AvatarDeleteResponse,
    ErrorResponse,
    VALID_ARRAY_FIELDS,
    FIELD_DISPLAY_NAMES,
)
from src.config.logger import get_logger
from src.config.settings import get_settings
from src.database import get_db, get_redis, Account, UserProfile, RefreshToken, UniversityProgram, UserLikedUniversity
from src.utils.session_utils import get_session
from src.utils.password_utils import hash_token
from src.utils.auth_deps import get_current_user_id
from src.services.dify_service import (
    upload_file_to_dify,
    run_cv_parsing_workflow,
    DifyUpstreamError,
)
from src.services.university_service import resolve_university_program

logger = get_logger(__name__)
settings = get_settings()

ALLOWED_CV_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

ALLOWED_AVATAR_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

AVATAR_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

router = APIRouter(prefix="/profile", tags=["Profile"])


async def _get_current_user_id(
    authorization: str,
    db: AsyncSession,
    redis: Optional[Redis],
) -> int:
    """Thin wrapper delegating to the shared helper."""
    return await get_current_user_id(authorization, db, redis)


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
    file: Optional[UploadFile] = File(None),
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        # ── Auth ──
        user_id = await _get_current_user_id(authorization, db, redis)

        # ── Validate file presence ──
        if file is None or not file.filename:
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
                detail={"message": f"File too large. Maximum size is {settings.cv_max_file_size // (1024 * 1024)} MB"},
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
        # Dify workflow may nest all fields under a "result" key
        if "result" in outputs and len(outputs) == 1:
            inner = outputs["result"]
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except (json.JSONDecodeError, TypeError):
                    inner = outputs
            if isinstance(inner, dict):
                outputs = inner

        personal = _parse_dify_personal_info(outputs)

        response = AllProfileResponse(
            personalInfo=PersonalInfoData(
                name=personal.get("name") or "",
                gender=personal.get("gender") or "",
                birthday=personal.get("birthday") or "",
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
                name=basic_info.get("name", ""),
                gender=basic_info.get("gender", ""),
                birthday=basic_info.get("birthday", ""),
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
            name=basic_info.get("name", ""),
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


# ──────────────────────────────────────────────
# Liked University Endpoints
# ──────────────────────────────────────────────


def _validate_uuid(unit_id: str) -> None:
    """Raise 422 if unit_id is not a valid UUID."""
    import uuid as _uuid
    try:
        _uuid.UUID(unit_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid university program ID format"},
        )


@router.post(
    "/liked-university/check",
    response_model=CheckFavoriteResponse,
    responses={
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Check Favorite University",
    description="Deduplicate the program card and return its stable unit_id with is_liked status.",
)
async def check_favorite_university(
    request: ProgramCardRequest,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        # Resolve (deduplicate) the program
        program = await resolve_university_program(db, request)

        # Check if liked
        result = await db.execute(
            select(UserLikedUniversity).where(
                UserLikedUniversity.user_id == user_id,
                UserLikedUniversity.university_program_id == program.id,
            )
        )
        is_liked = result.scalar_one_or_none() is not None

        await db.commit()
        return CheckFavoriteResponse(unit_id=program.id, is_liked=is_liked)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Check favorite university error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


@router.post(
    "/liked-university/{unit_id}",
    response_model=LikeResponse,
    responses={
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        404: {"description": "University program not found", "model": ErrorResponse},
        422: {"description": "Invalid unit_id format", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Like University Program",
    description="Add the specified university program to the current user's favorites. Idempotent.",
)
async def like_university_program(
    unit_id: str,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    _validate_uuid(unit_id)

    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        # Verify program exists
        result = await db.execute(
            select(UniversityProgram).where(UniversityProgram.id == unit_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "University program not found"},
            )

        # Idempotent insert
        result = await db.execute(
            select(UserLikedUniversity).where(
                UserLikedUniversity.user_id == user_id,
                UserLikedUniversity.university_program_id == unit_id,
            )
        )
        if not result.scalar_one_or_none():
            db.add(UserLikedUniversity(user_id=user_id, university_program_id=unit_id))

        await db.commit()
        logger.info(f"User {user_id} liked program {unit_id}")
        return LikeResponse(unit_id=unit_id, is_liked=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Like university error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


@router.delete(
    "/liked-university/{unit_id}",
    response_model=UnlikeResponse,
    responses={
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        422: {"description": "Invalid unit_id format", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Unlike University Program",
    description="Remove the specified university program from the current user's favorites. Idempotent.",
)
async def unlike_university_program(
    unit_id: str,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    _validate_uuid(unit_id)

    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        result = await db.execute(
            select(UserLikedUniversity).where(
                UserLikedUniversity.user_id == user_id,
                UserLikedUniversity.university_program_id == unit_id,
            )
        )
        record = result.scalar_one_or_none()
        if record:
            await db.delete(record)

        await db.commit()
        logger.info(f"User {user_id} unliked program {unit_id}")
        return UnlikeResponse(unit_id=unit_id, is_liked=False)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unlike university error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


@router.get(
    "/liked-university",
    response_model=LikedUniversityListResponse,
    responses={
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get Liked University List",
    description="Return all university programs liked by the current user, ordered by most recently liked first.",
)
async def get_liked_universities(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        result = await db.execute(
            select(UserLikedUniversity)
            .where(UserLikedUniversity.user_id == user_id)
            .order_by(UserLikedUniversity.created_at.desc())
        )
        liked_records = result.scalars().all()

        items = []
        for record in liked_records:
            # Fetch associated program
            prog_result = await db.execute(
                select(UniversityProgram).where(UniversityProgram.id == record.university_program_id)
            )
            program = prog_result.scalar_one_or_none()
            if program:
                items.append(
                    LikedUniversityItem(
                        unit_id=program.id,
                        liked_at=record.created_at.isoformat() if record.created_at else "",
                        program=program.program_data or {},
                    )
                )

        return LikedUniversityListResponse(data=items)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get liked universities error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


# ──────────────────────────────────────────────
# Avatar Upload & Delete
# ──────────────────────────────────────────────

def _avatar_dir() -> Path:
    """Return the avatar upload directory, creating it if needed."""
    p = Path(settings.avatar_upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _find_existing_avatar(user_id: int) -> Optional[Path]:
    """Find the user's existing avatar file regardless of extension."""
    avatar_dir = _avatar_dir()
    for ext in AVATAR_EXTENSIONS.values():
        candidate = avatar_dir / f"{user_id}{ext}"
        if candidate.exists():
            return candidate
    return None


@router.get(
    "/avatar",
    response_model=GetAvatarResponse,
    responses={
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Get Avatar URL",
    description="Returns the avatar URL for the authenticated user. "
                "If the user has no avatar, avatar_url will be null.",
)
async def get_avatar(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        avatar_url = None
        if profile and profile.basic_info:
            avatar_url = profile.basic_info.get("avatar")

        return GetAvatarResponse(avatar_url=avatar_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get avatar error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


@router.put(
    "/avatar",
    response_model=AvatarUploadResponse,
    responses={
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        413: {"description": "File too large", "model": ErrorResponse},
        415: {"description": "Unsupported file type", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Upload or Update Avatar",
    description="Upload an image file to set or replace the user's avatar. "
                "Only JPEG, PNG, and WebP formats are accepted. Maximum file size is 2 MB.",
)
async def upload_avatar(
    file: UploadFile = File(...),
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        # Validate content type
        if file.content_type not in ALLOWED_AVATAR_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail={"message": "Only JPEG, PNG, and WebP images are allowed"},
            )

        # Read and validate size
        file_content = await file.read()

        if len(file_content) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Uploaded file is empty"},
            )

        if len(file_content) > settings.avatar_max_file_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"message": f"File size exceeds {settings.avatar_max_file_size // (1024 * 1024)} MB limit"},
            )

        # Delete old avatar if extension differs
        ext = AVATAR_EXTENSIONS[file.content_type]
        existing = _find_existing_avatar(user_id)
        if existing is not None:
            existing.unlink(missing_ok=True)

        # Write new file
        avatar_path = _avatar_dir() / f"{user_id}{ext}"
        avatar_path.write_bytes(file_content)

        # Update basic_info.avatar in user profile
        avatar_url = f"/uploads/avatars/{user_id}{ext}"
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        if profile:
            basic_info = profile.basic_info or {}
            basic_info["avatar"] = avatar_url
            profile.basic_info = basic_info
            await db.commit()

        logger.info(f"Avatar uploaded for user_id={user_id}: {avatar_url}")
        return AvatarUploadResponse(message="Avatar uploaded successfully", avatar_url=avatar_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Avatar upload error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


@router.delete(
    "/avatar",
    response_model=AvatarDeleteResponse,
    responses={
        401: {"description": "Invalid or expired token", "model": ErrorResponse},
        404: {"description": "No avatar found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Delete Avatar",
    description="Remove the current user's avatar image from storage and profile.",
)
async def delete_avatar(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        existing = _find_existing_avatar(user_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "No avatar found"},
            )

        existing.unlink(missing_ok=True)

        # Clear avatar from basic_info
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if profile and profile.basic_info:
            basic_info = dict(profile.basic_info)
            basic_info.pop("avatar", None)
            profile.basic_info = basic_info
            await db.commit()

        logger.info(f"Avatar deleted for user_id={user_id}")
        return AvatarDeleteResponse(message="Avatar deleted successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Avatar delete error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )
