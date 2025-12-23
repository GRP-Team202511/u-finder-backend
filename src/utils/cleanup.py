"""
Database cleanup utility functions
Handles cleanup of expired temporary records
"""
from datetime import datetime, timezone
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import SignUpVerification, PasswordReset
from src.config.logger import get_logger

logger = get_logger(__name__)


async def cleanup_expired_verifications(db: AsyncSession) -> int:
    """
    Clean up expired signup verification records
    
    Args:
        db: Database session
    
    Returns:
        Number of records deleted
    """
    try:
        result = await db.execute(
            delete(SignUpVerification).where(
                SignUpVerification.expires_at < datetime.now(timezone.utc)
            )
        )
        await db.commit()
        deleted_count = result.rowcount
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired signup verification records")
        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up expired verifications: {str(e)}")
        await db.rollback()
        return 0


async def cleanup_expired_password_resets(db: AsyncSession) -> int:
    """
    Clean up expired password reset records
    
    Args:
        db: Database session
    
    Returns:
        Number of records deleted
    """
    try:
        result = await db.execute(
            delete(PasswordReset).where(
                PasswordReset.expires_at < datetime.now(timezone.utc)
            )
        )
        await db.commit()
        deleted_count = result.rowcount
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired password reset records")
        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up expired password resets: {str(e)}")
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
    verifications_deleted = await cleanup_expired_verifications(db)
    resets_deleted = await cleanup_expired_password_resets(db)
    
    return {
        "signup_verifications": verifications_deleted,
        "password_resets": resets_deleted,
        "total": verifications_deleted + resets_deleted
    }
