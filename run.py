import uvicorn
from src.config.logger import get_logger
from src.config.settings import get_settings

logger = get_logger(__name__)
settings = get_settings()

if __name__ == "__main__":
    logger.info("Starting U-Finder Backend server...")
    logger.info(f"App: {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Server address: http://{settings.server_host}:{settings.server_port}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Development mode: Hot reload {'enabled' if settings.reload else 'disabled'}")
    
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.reload,
        log_level=settings.log_level.lower()
    )
