"""
Redis session utility functions
Handles all Redis-based session operations for refresh token caching.

Key schema:
  session:{HMAC-SHA256(token)}   → Hash  { user_id, user_agent }   TTL = remaining token lifetime
  user_sessions:{user_id}        → Set   of HMAC-SHA256 digests    TTL = SESSION_TTL_SECONDS + buffer

The plain-text token is NEVER stored in Redis. The key is always the same
HMAC-SHA256 digest that is stored in the database (token_hashed column),
so Redis and PostgreSQL are always consistent. A compromised Redis instance
cannot yield usable session tokens.
"""
from typing import Optional
from redis.asyncio import Redis

from src.config.logger import get_logger
from src.utils.password_utils import hash_token

logger = get_logger(__name__)

# 30 days in seconds — matches refresh_token.expire_at default
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 2592000

# A small buffer so the index set outlives individual session keys
_INDEX_TTL_SECONDS = SESSION_TTL_SECONDS + 24 * 60 * 60  # 31 days


def _session_key(token: str) -> str:
    """token may be plain-text or already a digest — always hash it."""
    return f"session:{hash_token(token)}"


def _user_index_key(user_id: int) -> str:
    return f"user_sessions:{user_id}"


async def save_session(
    redis: Redis,
    token: str,
    user_id: int,
    user_agent: str,
    ttl_seconds: int = SESSION_TTL_SECONDS,
) -> None:
    """
    Store a session in Redis.

    The key is HMAC-SHA256(token), matching the token_hashed column in the DB.
    The plain-text token is never written to Redis.

    Args:
        redis:       Redis client
        token:       Plain-text refresh token
        user_id:     User's ID
        user_agent:  Client user-agent string
        ttl_seconds: Time-to-live in seconds (default: 30 days)
    """
    try:
        digest = hash_token(token)
        session_key = f"session:{digest}"
        index_key = _user_index_key(user_id)

        pipe = redis.pipeline()
        # Store session data — only non-secret fields
        pipe.hset(
            session_key,
            mapping={
                "user_id": str(user_id),
                "user_agent": user_agent,
            },
        )
        pipe.expire(session_key, ttl_seconds)
        # Track this digest under the user's index set
        pipe.sadd(index_key, digest)
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
        digest = hash_token(token)
        session_key = f"session:{digest}"

        # Fetch user_id before deleting so we can clean the index
        data = await redis.hgetall(session_key)

        pipe = redis.pipeline()
        pipe.delete(session_key)
        if data and "user_id" in data:
            # Index set stores digests, not plain tokens
            pipe.srem(_user_index_key(int(data["user_id"])), digest)
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
        for digest in tokens:
            # Index stores digests; key is already in "session:{digest}" form
            pipe.delete(f"session:{digest}")
        pipe.delete(index_key)
        await pipe.execute()

        count = len(tokens)
        logger.info(f"Deleted {count} Redis sessions for user_id={user_id}")
        return count
    except Exception as e:
        logger.error(f"Failed to delete all sessions for user_id={user_id}: {str(e)}")
        return 0
