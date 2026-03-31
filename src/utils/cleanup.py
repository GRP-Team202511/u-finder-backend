# This code was completed by GRP Team 2025.11.
"""
Database cleanup utility functions
Handles cleanup of expired temporary records
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from src.database import TempToken
from src.config.logger import get_logger

logger = get_logger(__name__)


async def cleanup_expired_temp_tokens(db: AsyncSession) -> int:
    """
    Clean up expired temporary tokens (email verification, password reset, etc.)
    
    Args:
        db: Database session
    
    Returns:
        Number of records deleted
    """
    try:
        result = await db.execute(
            delete(TempToken).where(
                TempToken.expire_at < datetime.now(timezone.utc)
            )
        )
        await db.commit()
        deleted_count = result.rowcount
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired temporary token records")
        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up expired temp tokens: {str(e)}")
        await db.rollback()
        return 0


async def cleanup_expired_refresh_tokens(
    db: AsyncSession,
    redis: Optional[Redis] = None,
) -> int:
    """
    Clean up expired refresh tokens from the database.
    When a Redis client is provided, also removes the corresponding
    session cache entries so stale keys don't linger in Redis.

    Args:
        db:    Database session
        redis: Optional Redis client for cache invalidation

    Returns:
        Number of records deleted
    """
    try:
        from src.database import RefreshToken

        now = datetime.now(timezone.utc)

        # If Redis is available, fetch expired records first so we can
        # identify and remove their cache entries before bulk-deleting.
        if redis is not None:
            result = await db.execute(
                select(RefreshToken).where(RefreshToken.expire_at < now)
            )
            expired_records = result.scalars().all()

            if expired_records:
                # The digest stored in user_sessions:{uid} IS token_hashed
                # (both are HMAC-SHA256 of the plain token), so we can delete
                # Redis keys directly without calling get_session().
                pipe = redis.pipeline()
                for rt in expired_records:
                    pipe.delete(f"session:{rt.token_hashed}")
                    pipe.srem(f"user_sessions:{rt.user_id}", rt.token_hashed)
                await pipe.execute()

        # Bulk delete expired records from DB
        result = await db.execute(
            delete(RefreshToken).where(RefreshToken.expire_at < now)
        )
        await db.commit()
        deleted_count = result.rowcount
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired refresh token records")
        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up expired refresh tokens: {str(e)}")
        await db.rollback()
        return 0


async def cleanup_all_expired_records(
    db: AsyncSession,
    redis: Optional[Redis] = None,
) -> dict:
    """
    Clean up all expired temporary records.

    Args:
        db:    Database session
        redis: Optional Redis client; passed through to refresh-token cleanup
               for cache invalidation

    Returns:
        Dictionary with cleanup results
    """
    temp_tokens_deleted = await cleanup_expired_temp_tokens(db)
    refresh_tokens_deleted = await cleanup_expired_refresh_tokens(db, redis=redis)

    return {
        "temp_tokens": temp_tokens_deleted,
        "refresh_tokens": refresh_tokens_deleted,
        "total": temp_tokens_deleted + refresh_tokens_deleted,
    }
