"""
Database cleanup utility functions
Handles cleanup of expired temporary records
"""
from datetime import datetime, timezone
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

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


async def cleanup_expired_refresh_tokens(db: AsyncSession) -> int:
    """
    Clean up expired refresh tokens
    
    Args:
        db: Database session
    
    Returns:
        Number of records deleted
    """
    try:
        from src.database import RefreshToken
        result = await db.execute(
            delete(RefreshToken).where(
                RefreshToken.expire_at < datetime.now(timezone.utc)
            )
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


async def cleanup_all_expired_records(db: AsyncSession) -> dict:
    """
    Clean up all expired temporary records
    
    Args:
        db: Database session
    
    Returns:
        Dictionary with cleanup results
    """
    temp_tokens_deleted = await cleanup_expired_temp_tokens(db)
    refresh_tokens_deleted = await cleanup_expired_refresh_tokens(db)
    
    return {
        "temp_tokens": temp_tokens_deleted,
        "refresh_tokens": refresh_tokens_deleted,
        "total": temp_tokens_deleted + refresh_tokens_deleted
    }
