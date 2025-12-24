import os
import structlog    #type: ignore
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging():
    
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = os.getenv("LOG_FILE", "/logs/ds-service.log")
    environment = os.getenv("ENVIRONMENT", "dev")
    
    # Ensure log directory exists
    log_path = Path(log_file).parent
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Shared processors for both structlog and standard logging
    # These process the log record but don't render to JSON yet
    shared_processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    
    # Configure structlog for stdlib integration
    # When using stdlib integration, structlog outputs dicts to logging system
    # ProcessorFormatter will handle JSON rendering and wrapping
    # wrap_for_formatter is required to properly integrate with standard logging
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging handlers
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    
    # File handler with rotation (10MB per file, keep 5 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    
    # Console handler (stdout)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    
    # ProcessorFormatter applies JSONRenderer as final step for both structlog and standard logging
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),  # Final JSON renderer
        foreign_pre_chain=shared_processors,  # Processors for non-structlog loggers
    )
    file_handler.setFormatter(json_formatter)
    console_handler.setFormatter(json_formatter)
    
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Enable uvicorn access logs at INFO level
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    # Set default context variables (service and environment)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        service="ds-service",
        environment=environment
    )
    
    return root_logger