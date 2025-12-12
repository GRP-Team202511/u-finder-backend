import uvicorn
from src.config.logger import get_logger

logger = get_logger(__name__)

if __name__ == "__main__":
    logger.info("Starting U-Finder Backend server...")
    logger.info("Server address: http://0.0.0.0:8000")
    logger.info("Development mode: Hot reload enabled")
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
