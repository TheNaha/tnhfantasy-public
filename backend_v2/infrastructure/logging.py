# Structured logging configuration using structlog
# Provides consistent, formatted logs for better analysis

import logging
import sys
from typing import Optional
import structlog


# ANSI color codes for terminal output
class Colors:
    RESET = "\033[0m"
    GRAY = "\033[90m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    BOLD = "\033[1m"


def compact_renderer(logger, method_name, event_dict):
    """
    Custom compact two-line renderer for pretty console output.
    
    Format:
    ┌ 11:07:07 INFO  http_request
    └ path=/api/jobs/queue status=200 duration=2.21ms
    """
    # Extract standard fields
    timestamp = event_dict.pop("timestamp", "")
    level = event_dict.pop("level", "info").upper()
    event = event_dict.pop("event", "")
    logger_name = event_dict.pop("logger_name", "")
    
    # Color based on level
    level_colors = {
        "DEBUG": Colors.GRAY,
        "INFO": Colors.GREEN,
        "WARNING": Colors.YELLOW,
        "ERROR": Colors.RED,
        "CRITICAL": Colors.RED + Colors.BOLD,
    }
    level_color = level_colors.get(level, Colors.RESET)
    
    # Format timestamp (just time portion for compactness)
    if timestamp:
        # Extract just HH:MM:SS if full timestamp
        time_part = timestamp.split(" ")[-1] if " " in timestamp else timestamp
    else:
        time_part = ""
    
    # Build key-value string for second line
    kv_parts = []
    for key, value in event_dict.items():
        if key.startswith("_"):  # Skip internal keys
            continue
        # Special formatting for common keys
        if key == "duration_ms":
            kv_parts.append(f"{Colors.CYAN}{value}ms{Colors.RESET}")
        elif key == "status_code":
            status_color = Colors.GREEN if value < 400 else Colors.YELLOW if value < 500 else Colors.RED
            kv_parts.append(f"{status_color}{value}{Colors.RESET}")
        elif key == "method":
            kv_parts.append(f"{Colors.MAGENTA}{value}{Colors.RESET}")
        elif key == "path":
            kv_parts.append(f"{value}")
        elif key == "request_id":
            kv_parts.append(f"{Colors.GRAY}#{value}{Colors.RESET}")
        else:
            kv_parts.append(f"{key}={value}")
    
    # Build output
    line1 = f"{Colors.GRAY}┌{Colors.RESET} {Colors.GRAY}{time_part}{Colors.RESET} {level_color}{level:5}{Colors.RESET} {Colors.BOLD}{event}{Colors.RESET}"
    
    if kv_parts:
        kv_str = " ".join(kv_parts)
        line2 = f"{Colors.GRAY}└{Colors.RESET} {kv_str}"
        return f"{line1}\n{line2}"
    else:
        return line1


def configure_logging(
    log_level: str = "INFO",
    json_format: bool = False,
    timestamp_fmt: str = "%Y-%m-%d %H:%M:%S"
):
    """
    Configure structured logging for the application.
    
    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Output logs as JSON (better for production/log aggregation)
        timestamp_fmt: Timestamp format for console output
    """
    # Set up standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO)
    )
    
    # Configure structlog processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt=timestamp_fmt, utc=False),
    ]
    
    if json_format:
        # JSON format for production
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer()
        ]
    else:
        # Compact two-line format for development
        processors = shared_processors + [
            compact_renderer
        ]
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    
    # Silence noisy loggers to reduce log spam
    # Uvicorn access logs - we use our own request logging middleware
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    # httpx logs - "HTTP Request: POST http://..." messages
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    # APScheduler - suppress job execution details, only show warnings
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)


def get_logger(name: Optional[str] = None) -> structlog.BoundLogger:
    """
    Get a structured logger instance.
    
    Args:
        name: Optional logger name (will be added to log context)
        
    Returns:
        Bound structlog logger
        
    Usage:
        logger = get_logger("job_service")
        logger.info("job_created", job_id="123", status="pending")
    """
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(logger_name=name)
    return logger


# Convenience loggers for common modules
def job_logger() -> structlog.BoundLogger:
    """Get logger for job-related operations."""
    return get_logger("jobs")


def provider_logger() -> structlog.BoundLogger:
    """Get logger for provider-related operations."""
    return get_logger("providers")


def model_logger() -> structlog.BoundLogger:
    """Get logger for model-related operations."""
    return get_logger("models")


def download_logger() -> structlog.BoundLogger:
    """Get logger for download-related operations."""
    return get_logger("downloads")


def api_logger() -> structlog.BoundLogger:
    """Get logger for API-related operations."""
    return get_logger("api")


def cache_logger() -> structlog.BoundLogger:
    """Get logger for cache-related operations."""
    return get_logger("cache")


def db_logger() -> structlog.BoundLogger:
    """Get logger for database-related operations."""
    return get_logger("database")


def scheduler_logger() -> structlog.BoundLogger:
    """Get logger for scheduler-related operations."""
    return get_logger("scheduler")


def http_logger() -> structlog.BoundLogger:
    """Get logger for HTTP client operations."""
    return get_logger("http_client")


def config_logger() -> structlog.BoundLogger:
    """Get logger for configuration operations."""
    return get_logger("config")


def ws_logger() -> structlog.BoundLogger:
    """Get logger for WebSocket operations."""
    return get_logger("websocket")


# Initialize with default settings
configure_logging()

