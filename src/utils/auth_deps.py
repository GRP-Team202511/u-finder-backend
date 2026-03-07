"""
Shared authentication dependency.

Extracts and verifies the refresh token from the Authorization header,
returning the associated user_id.  Used by profile and chat routers.
"""
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.database.models import RefreshToken
from src.utils.session_utils import get_session
from src.utils.password_utils import hash_token


async def get_current_user_id(
    authorization: str,
    db: AsyncSession,
    redis: Optional[Redis],
) -> int:
    """
    Extract and verify the refresh token from Authorization header.
    Returns the user_id associated with the session.

    1. Try Redis cache first (fast path).
    2. Fallback to DB lookup on cache miss.
    3. Raise HTTP 401 if token is invalid.
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
