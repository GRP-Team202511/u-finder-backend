from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import time
from src.config.logger import get_logger
from src.config.settings import get_settings

# Initialize logger and settings
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("=" * 50)
    logger.info(f"U-Finder Backend Application Started - {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.environment}")
    logger.info("=" * 50)
    yield
    # Shutdown
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


@app.get("/")
async def root():
    logger.info("Root path accessed")
    return {"message": "Hello World"}
