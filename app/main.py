"""
U-Finder Backend Main Application
FastAPI application entry point
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import time
import asyncio
from src.database.connection import init_db, AsyncSessionLocal
from src.database.redis_connection import init_redis, close_redis
from src.config.logger import get_logger
from src.routers import auth_router
from src.config.settings import get_settings
from src.utils import cleanup_all_expired_records

# Initialize logger and settings
logger = get_logger(__name__)
settings = get_settings()

# Background task flag
cleanup_task = None


async def periodic_cleanup():
    """Periodically clean up expired records every hour"""
    while True:
        try:
            await asyncio.sleep(3600)  # Wait 1 hour
            logger.info("Running periodic cleanup of expired records...")
            async with AsyncSessionLocal() as db:
                result = await cleanup_all_expired_records(db)
                logger.info(f"Cleanup completed: {result}")
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {str(e)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle management
    Handles startup and shutdown events
    """
    global cleanup_task
    
    # Startup event
    logger.info("=" * 50)
    logger.info(f"U-Finder Backend Application Started - {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.environment}")
    logger.info("=" * 50)
    
    # Initialize database
    logger.info("Initializing database...")
    try:
        await init_db()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}")
        logger.warning("⚠️  Application will start without database connection")
        logger.warning("⚠️  Auth endpoints will not work until database is configured")

    # Initialize Redis
    logger.info("Initializing Redis...")
    try:
        await init_redis()
        logger.info("✅ Redis initialized successfully")
    except Exception as e:
        logger.error(f"❌ Redis initialization failed: {str(e)}")
        logger.warning("⚠️  Application will start without Redis — session validation falls back to database")

    # Start background cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup())
    logger.info("🔄 Background cleanup task started")
    
    yield
    
    # Shutdown event
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("Background cleanup task stopped")

    # Close Redis connection
    await close_redis()
    logger.info("Redis connection closed")

    logger.info("=" * 50)
    logger.info("U-Finder Backend Application Shutdown")
    logger.info("=" * 50)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan
)

# CORS configuration from environment variables
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=settings.cors_credentials,
    allow_methods=settings.cors_methods.split(",") if settings.cors_methods != "*" else ["*"],
    allow_headers=settings.cors_headers.split(",") if settings.cors_headers != "*" else ["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests"""
    start_time = time.time()
    
    # Log request info
    logger.info(f"Request started: {request.method} {request.url.path}")
    
    # Process request
    response = await call_next(request)
    
    # Calculate process time
    process_time = time.time() - start_time
    
    # Log response info
    logger.info(
        f"Request completed: {request.method} {request.url.path} - "
        f"Status: {response.status_code} - Time: {process_time:.3f}s"
    )
    
    return response


# Include routers
app.include_router(auth_router)


# Root path
@app.get("/", tags=["Basic"])
async def root():
    """Root path endpoint"""
    logger.info("Root path accessed")
    return {
        "message": "Welcome to U-Finder Backend API",
        "version": settings.app_version,
        "docs": "/docs"
    }


# Health check
@app.get("/health", tags=["Basic"])
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "u-finder-backend"}


# Admin endpoint for manual cleanup
@app.post("/admin/cleanup", tags=["Admin"])
async def manual_cleanup():
    """Manually trigger cleanup of expired records"""
    logger.info("Manual cleanup triggered")
    async with AsyncSessionLocal() as db:
        result = await cleanup_all_expired_records(db)
    logger.info(f"Manual cleanup completed: {result}")
    return {
        "status": "success",
        "message": "Cleanup completed",
        "deleted": result
    }
