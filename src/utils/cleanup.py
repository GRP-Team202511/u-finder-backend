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
        from src.utils.session_utils import get_session, delete_session

        now = datetime.now(timezone.utc)

        # If Redis is available, fetch expired records first so we can
        # identify and remove their cache entries before bulk-deleting.
        if redis is not None:
            result = await db.execute(
                select(RefreshToken).where(RefreshToken.expire_at < now)
            )
            expired_records = result.scalars().all()

            if expired_records:
                # Build a set of token_hashed values that are about to be deleted
                expired_hashes = {rt.token_hashed for rt in expired_records}
                affected_user_ids = {rt.user_id for rt in expired_records}

                # For each affected user walk their Redis index set and evict
                # any session whose stored token_hashed is in the expired set.
                for user_id in affected_user_ids:
                    index_key = f"user_sessions:{user_id}"
                    tokens = await redis.smembers(index_key)
                    for token in tokens:
                        cached = await get_session(redis, token)
                        if cached and cached.get("token_hashed") in expired_hashes:
                            await delete_session(redis, token)

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
