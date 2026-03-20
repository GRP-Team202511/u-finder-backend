from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from typing import AsyncGenerator
import os
from src.config import get_settings


# Database configuration
settings = get_settings()
DATABASE_URL = settings.database_url

# Read echo setting from environment variable (default: False)
DATABASE_ECHO = os.getenv("DATABASE_ECHO", "False").lower() in ("1", "true", "yes", "on")

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=DATABASE_ECHO,  # Controlled by DATABASE_ECHO env var
    future=True,
    pool_pre_ping=True,  # Enable connection health checks
    pool_size=5,         # Connection pool size
    max_overflow=10      # Maximum overflow connections
)

# Create async session maker
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Initialize database - create all tables"""
    try:
        async with engine.begin() as conn:
            # Development-only reset: explicitly opt-in via settings.
            if settings.is_development and settings.db_drop_all_on_startup:
                await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        # Re-raise the exception to be handled by the caller
        raise Exception(f"Failed to initialize database: {str(e)}")