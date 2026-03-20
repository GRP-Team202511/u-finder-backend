"""
Redis connection module
Manages async Redis client and connection pool
"""
from typing import AsyncGenerator, Optional
import redis.asyncio as aioredis
from redis.asyncio import Redis

from src.config.settings import get_settings
from src.config.logger import get_logger

logger = get_logger(__name__)

settings = get_settings()

# Global Redis client instance
redis_client: Optional[Redis] = None


async def init_redis() -> None:
    """
    Initialize the Redis connection pool.
    Should be called once at application startup.
    """
    global redis_client
    try:
        redis_client = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password or None,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        # Verify connection
        await redis_client.ping()
        logger.info(
            f"Redis connection established: {settings.redis_host}:{settings.redis_port} db={settings.redis_db}"
        )
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {str(e)}")
        raise


async def close_redis() -> None:
    """
    Close the Redis connection.
    Should be called at application shutdown.
    """
    global redis_client
    if redis_client:
        await redis_client.aclose()
        redis_client = None
        logger.info("Redis connection closed")


async def get_redis() -> AsyncGenerator[Optional[Redis], None]:
    """
    FastAPI dependency for getting the Redis client.
    Reuses the global connection pool.
    """
    yield redis_client
