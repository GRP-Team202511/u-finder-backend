import sys
import os
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest
import pytest_asyncio
from typing import AsyncGenerator
from redis.asyncio import Redis, from_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from src.database.connection import get_db, Base
from src.database.redis_connection import get_redis
from src.config.settings import get_settings
from src.routers import auth_router, profile_router, chat_router, two_factor_router, admin_router, passkey_router

@pytest.fixture(autouse=True, scope="session")
def _integration_env():
    """
    Ensure a deterministic environment and settings configuration for integration tests.
    This fixture ensures TOTP_ENCRYPTION_KEY is securely populated to test environments.
    """
    os.environ["TOTP_ENCRYPTION_KEY"] = "n5lbJGQ1/ODh4HUNavgzf1GFIK9f/n1yTlPRGntIrsU="
    get_settings.cache_clear()
    get_settings()
    yield
    get_settings.cache_clear()

settings = get_settings()

# ==============================================================================
# Configuration
# ==============================================================================
# Use default DB config from settings, but potentially append something if needed
# We rely on settings.database_url
TEST_DB_URL = settings.database_url

# For Redis, use a different DB (e.g., db=15) to avoid thrashing dev sessions
redis_auth = f":{settings.redis_password}@" if settings.redis_password else ""
TEST_REDIS_URL = f"redis://{redis_auth}{settings.redis_host}:{settings.redis_port}/15"

# Setup real async engine
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)

# ==============================================================================
# FastAPI standalone app for integration tests
# ==============================================================================
def build_integration_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(chat_router)
    app.include_router(two_factor_router)
    app.include_router(admin_router)
    app.include_router(passkey_router)
    return app

integration_app = build_integration_app()

# ==============================================================================
# Essential Fixtures
# ==============================================================================

@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database():
    """Ensure all tables exist before tests start (creates if missing)."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Could optionally drop tables here if we used a test-only container, 
    # but we DO NOT drop them here since it's the development container.

@pytest_asyncio.fixture
async def real_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Returns an AsyncSession coupled to a transaction that rolls back at the end.
    This guarantees NO GARBAGE DATA is left in the development database.
    """
    async with test_engine.connect() as conn:
        transaction = await conn.begin()
        
        # A nested transaction utilizing a SQL SAVEPOINT
        await conn.begin_nested()
        
        session = AsyncSession(conn, expire_on_commit=False)
        
        from sqlalchemy import event
        @event.listens_for(session.sync_session, "after_transaction_end")
        def end_savepoint(session, transaction):
            # If the application commits the session, restart a nested transaction
            # so the outer transaction is never committed natively by the app.
            nonlocal conn
            if not conn.in_nested_transaction():
                conn.sync_connection.begin_nested()

        yield session

        # Tear down
        await session.close()
        # Roll back everything that happened in the scope of this connection
        await transaction.rollback()


@pytest_asyncio.fixture
async def real_redis() -> AsyncGenerator[Redis, None]:
    """
    Returns a real Async Redis client, isolated to db 15.
    Flushes the db before and after every test.
    """
    redis_client = await from_url(TEST_REDIS_URL, decode_responses=True)
    await redis_client.flushdb()
    
    yield redis_client
    
    await redis_client.flushdb()
    await redis_client.close()


@pytest_asyncio.fixture
async def integration_client(real_db: AsyncSession, real_redis: Redis) -> AsyncGenerator[AsyncClient, None]:
    """
    Returns an AsyncClient with real dependencies injected.
    Overrides fastapi `Depends` functions so routers use `real_db` and `real_redis`.
    """
    # Overrides for dependencies
    async def override_get_db():
        yield real_db
        
    async def override_get_redis():
        yield real_redis
        
    integration_app.dependency_overrides[get_db] = override_get_db
    integration_app.dependency_overrides[get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=integration_app),
        base_url="http://test"
    ) as client:
        yield client

    # Cleanup overrides
    integration_app.dependency_overrides.clear()
