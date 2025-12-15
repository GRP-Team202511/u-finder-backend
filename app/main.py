"""
U-Finder Backend Main Application
FastAPI application entry point
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import time
from src.config.logger import get_logger
from src.config.settings import get_settings
from src.database import init_db
from src.routers import auth_router

# Initialize logger and settings
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle management
    Handles startup and shutdown events
    """
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
    
    yield
    
    # Shutdown event
    logger.info("=" * 50)
    logger.info("U-Finder Backend Application Shutdown")
    logger.info("=" * 50)


# Create FastAPI application instance
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
    
    logger.info(f"Request started: {request.method} {request.url.path}")
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    logger.info(
        f"Request completed: {request.method} {request.url.path} - "
        f"Status: {response.status_code} - Time: {process_time:.3f}s"
    )
    
    return response


# Register routers
app.include_router(auth_router)


# Root path
@app.get("/", tags=["Basic"])
async def root():
    """Root path endpoint"""
    logger.info("Root path accessed")
    return {
        "message": "Welcome to U-Finder Backend API",
        "version": "1.0.0",
        "docs": "/docs"
    }


# 健康检查
@app.get("/health", tags=["Basic"])
async def health_check():
    """健康检查接口"""
    return {"status": "healthy", "service": "u-finder-backend"}
