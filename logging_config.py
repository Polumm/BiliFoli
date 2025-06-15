import logging
import sys
from typing import Optional

def setup_logging(
    service_name: str,
    log_level: str = "INFO",
    log_format: Optional[str] = None
) -> logging.Logger:
    """
    Set up logging configuration for a service.
    
    Args:
        service_name: Name of the service for logging identification
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Optional custom log format
        
    Returns:
        Configured logger instance
    """
    if log_format is None:
        log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f"{service_name}.log")
        ]
    )
    
    # Create and return service logger
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, log_level.upper()))
    
    return logger

def get_logger(service_name: str) -> logging.Logger:
    """
    Get a configured logger for a service.
    
    Args:
        service_name: Name of the service for logging identification
        
    Returns:
        Configured logger instance
    """
    return logging.getLogger(service_name) 