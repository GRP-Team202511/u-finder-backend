"""
Redis session utility functions
Handles all Redis-based session operations for refresh token caching.

Key schema:
  session:{token}           → Hash  { user_id, user_agent }   TTL = remaining token lifetime
  user_sessions:{user_id}   → Set   of active token strings   TTL = SESSION_TTL_SECONDS + buffer
"""
from typing import Optional
from redis.asyncio import Redis

from src.config.logger import get_logger

logger = get_logger(__name__)

# 30 days in seconds — matches refresh_token.expire_at default
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 2592000

# A small buffer so the index set outlives individual session keys
_INDEX_TTL_SECONDS = SESSION_TTL_SECONDS + 24 * 60 * 60  # 31 days


def _session_key(token: str) -> str:
    return f"session:{token}"


def _user_index_key(user_id: int) -> str:
    return f"user_sessions:{user_id}"


async def save_session(
    redis: Redis,
    token: str,
    user_id: int,
    user_agent: str,
    token_hashed: str = "",
    ttl_seconds: int = SESSION_TTL_SECONDS,
) -> None:
    """
    Store a session in Redis.

    Args:
        redis:        Redis client
        token:        Plain-text refresh token (used as cache key)
        user_id:      User's ID
        user_agent:   Client user-agent string
        token_hashed: bcrypt hash stored in DB; kept here so logout can do
                      an exact DB lookup instead of a full-table bcrypt scan
        ttl_seconds:  Time-to-live in seconds (default: 30 days)
    """
    try:
        session_key = _session_key(token)
        index_key = _user_index_key(user_id)

        pipe = redis.pipeline()
        # Store session data as a hash
        pipe.hset(
            session_key,
            mapping={
                "user_id": str(user_id),
                "user_agent": user_agent,
                "token_hashed": token_hashed,
            },
        )
        pipe.expire(session_key, ttl_seconds)
        # Track this token under the user's index set
        pipe.sadd(index_key, token)
        pipe.expire(index_key, _INDEX_TTL_SECONDS)
        await pipe.execute()

        logger.debug(f"Session saved to Redis for user_id={user_id}, ttl={ttl_seconds}s")
    except Exception as e:
        # Non-fatal: log and continue — DB is the source of truth
        logger.error(f"Failed to save session to Redis: {str(e)}")


async def get_session(redis: Redis, token: str) -> Optional[dict]:
    """
    Retrieve a session from Redis.

    Args:
        redis: Redis client
        token: Plain-text refresh token

    Returns:
        Dict with ``user_id`` (int) and ``user_agent`` (str), or None on cache miss.
    """
    try:
        data = await redis.hgetall(_session_key(token))
        if not data:
            return None
        return {
            "user_id": int(data["user_id"]),
            "user_agent": data.get("user_agent", ""),
            "token_hashed": data.get("token_hashed", ""),
        }
    except Exception as e:
        logger.error(f"Failed to get session from Redis: {str(e)}")
        return None


async def delete_session(redis: Redis, token: str) -> None:
    """
    Delete a single session from Redis.
    Also removes the token from the owning user's index set.

    Args:
        redis: Redis client
        token: Plain-text refresh token
    """
    try:
        session_key = _session_key(token)

        # Fetch user_id before deleting so we can clean the index
        data = await redis.hgetall(session_key)

        pipe = redis.pipeline()
        pipe.delete(session_key)
        if data and "user_id" in data:
            pipe.srem(_user_index_key(int(data["user_id"])), token)
        await pipe.execute()

        logger.debug(f"Session deleted from Redis for token (user_id={data.get('user_id', '?')})")
    except Exception as e:
        logger.error(f"Failed to delete session from Redis: {str(e)}")


async def delete_all_user_sessions(redis: Redis, user_id: int) -> int:
    """
    Delete ALL cached sessions for a given user (e.g. forced sign-out all devices).

    Args:
        redis:   Redis client
        user_id: User's ID

    Returns:
        Number of session keys deleted.
    """
    try:
        index_key = _user_index_key(user_id)
        tokens = await redis.smembers(index_key)

        if not tokens:
            return 0

        pipe = redis.pipeline()
        for token in tokens:
            pipe.delete(_session_key(token))
        pipe.delete(index_key)
        await pipe.execute()

        count = len(tokens)
        logger.info(f"Deleted {count} Redis sessions for user_id={user_id}")
        return count
    except Exception as e:
        logger.error(f"Failed to delete all sessions for user_id={user_id}: {str(e)}")
        return 0
