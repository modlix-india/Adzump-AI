import os
import logging
import structlog  # type: ignore
import structlog.contextvars
from logging.handlers import RotatingFileHandler
from pathlib import Path
from structlog.types import EventDict


LEADING_KEYS = ("timestamp", "level", "logger", "msg")


def _drop_health_check_logs(_logger, _method: str, event_dict: EventDict) -> EventDict:
    event = event_dict.get("event", "")
    if "/health" in event:
        raise structlog.DropEvent
    return event_dict


def _reorder_keys(_logger, _method: str, event_dict: EventDict) -> EventDict:
    ordered: dict = {}
    for key in LEADING_KEYS:
        if key in event_dict:
            ordered[key] = event_dict.pop(key)
    ordered.update(event_dict)
    return ordered


def setup_logging():

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = os.getenv("LOG_FILE", "/logs/ds-service.log")
    environment = os.getenv("ENVIRONMENT", "local")
    enable_file_logging = environment != "local"

    if enable_file_logging:
        log_path = Path(log_file).parent
        log_path.mkdir(parents=True, exist_ok=True)

    # Processors for structlog loggers
    structlog_processors = [
        structlog.contextvars.merge_contextvars,
        _drop_health_check_logs,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.EventRenamer(to="msg"),
        _reorder_keys,
    ]

    # Processors for foreign (non-structlog) loggers - no filter_by_level
    foreign_processors = [
        structlog.contextvars.merge_contextvars,
        _drop_health_check_logs,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.EventRenamer(to="msg"),
        _reorder_keys,
    ]

    # Configure structlog for stdlib integration
    structlog.configure(
        processors=structlog_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard logging handlers (root logger)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    # ProcessorFormatter applies JSONRenderer as final step
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=foreign_processors,
    )

    # File handler — only in deployed environments (dev/stage/prod)
    # Locally there's no Grafana/Loki scraping log files
    file_handler = None
    if enable_file_logging:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(json_formatter)
        root_logger.addHandler(file_handler)

    # Console handler (stdout)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)

    if environment == "local":
        console_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(),
            foreign_pre_chain=foreign_processors,
        )
    else:
        console_formatter = json_formatter
    console_handler.setFormatter(console_formatter)

    root_logger.addHandler(console_handler)

    # Route uvicorn logs through the same handlers
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers.clear()
    uvicorn_access.setLevel(logging.WARNING)
    uvicorn_access.propagate = False

    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.handlers.clear()
    if file_handler:
        uvicorn_error.addHandler(file_handler)
    uvicorn_error.addHandler(console_handler)
    uvicorn_error.setLevel(logging.WARNING)
    uvicorn_error.propagate = False

    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        service="ds-service",
        environment=environment,
    )

    return root_logger
