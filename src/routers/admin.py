"""
Admin router module
Contains endpoints for admin user management
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Header, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from redis.asyncio import Redis

from src.schemas.admin import AdminUserResponse, ErrorResponse
from src.config.logger import get_logger
from src.database import get_db, get_redis, Account
from src.utils.auth_deps import get_current_user_id

logger = get_logger(__name__)

ADMIN_USER_TYPE = 3

router = APIRouter(prefix="/admin", tags=["Admin Users"])


async def _get_current_user_id(
    authorization: str,
    db: AsyncSession,
    redis: Optional[Redis],
) -> int:
    """Thin wrapper delegating to the shared helper."""
    return await get_current_user_id(authorization, db, redis)


def _derive_status(account: Account) -> str:
    """Derive user status from account flags."""
    if account.is_blocked:
        return "blocked"
    if not account.email_verified:
        return "pending"
    return "active"


def _derive_available_actions(user_status: str) -> List[str]:
    """Determine available moderation actions based on user status."""
    if user_status == "blocked":
        return ["unblock", "delete"]
    return ["block", "delete"]


@router.get(
    "/users",
    response_model=List[AdminUserResponse],
    responses={
        401: {"description": "Missing, malformed, or expired Bearer token", "model": ErrorResponse},
        403: {"description": "Valid token but user is not admin", "model": ErrorResponse},
    },
    summary="List users",
)
async def list_users(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """Returns a list of all user accounts for admin management."""
    try:
        user_id = await _get_current_user_id(authorization, db, redis)

        # Verify the caller is an admin
        result = await db.execute(
            select(Account).where(Account.user_id == user_id)
        )
        admin_account = result.scalar_one_or_none()

        if not admin_account or admin_account.user_type != ADMIN_USER_TYPE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "Admin permission required"},
            )

        # Fetch all user accounts
        result = await db.execute(select(Account))
        accounts = result.scalars().all()

        users = []
        for account in accounts:
            user_status = _derive_status(account)
            users.append(
                AdminUserResponse(
                    id=account.user_id,
                    name=account.user_name,
                    email=account.email,
                    type=str(account.user_type),
                    status=user_status,
                    created_at=account.created_at,
                    available_actions=_derive_available_actions(user_status),
                )
            )

        return users

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing users: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )
