# This code was completed by GRP Team 2025.11.
"""
Logger configuration module
Provides unified logging functionality with console and file output
"""
import logging
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler


# Logger configuration
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Log file configuration
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"
BACKUP_COUNT = 30  # Keep 30 days of logs


def setup_logger(name: str = None, level: int = LOG_LEVEL) -> logging.Logger:
    """
    Setup and return a logger instance
    
    Args:
        name: Logger name, typically use __name__
        level: Log level, default is INFO
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name or __name__)
    
    # Return if logger already has handlers (avoid duplicate handlers)
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    logger.propagate = False
    
    # Create formatter
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler with daily rotation at midnight (UTC)
    file_handler = TimedRotatingFileHandler(
        LOG_FILE,
        when='midnight',
        interval=1,
        backupCount=BACKUP_COUNT,
        encoding='utf-8',
        utc=True,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = None) -> logging.Logger:
    """
    Convenient function to get logger instance
    
    Args:
        name: Logger name, recommend passing __name__
        
    Returns:
        Logger instance
        
    Example:
        from src.config.logger import get_logger
        logger = get_logger(__name__)
        logger.info("This is a log message")
    """
    return setup_logger(name)


# Create default logger instance
default_logger = get_logger("u-finder")
