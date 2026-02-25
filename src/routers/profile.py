"""
Profile router module
Contains endpoints for user profile management
"""
from fastapi import APIRouter, HTTPException, Header, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from redis.asyncio import Redis

from src.schemas.profile import (
    PersonalInfoResponse,
    UpdatePersonalInfoRequest,
    UpdatePersonalInfoResponse,
    ErrorResponse,
)
from src.config.logger import get_logger
from src.database import get_db, get_redis, Account, UserProfile, RefreshToken
from src.utils.session_utils import get_session
from src.utils.password_utils import hash_token

logger = get_logger(__name__)

router = APIRouter(prefix="/profile", tags=["Profile"])


async def _get_current_user_id(
    authorization: str,
    db: AsyncSession,
    redis: Redis,
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
    redis: Redis = Depends(get_redis),
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
    redis: Redis = Depends(get_redis),
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
