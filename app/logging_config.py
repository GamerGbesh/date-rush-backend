"""
Centralized logging configuration for Date Rush backend.
"""

import logging
import sys

DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s - %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_level: str = "INFO",
    log_format: str = DEFAULT_LOG_FORMAT,
    date_format: str = DEFAULT_DATE_FORMAT,
) -> None:
    """
    Configure the root logger and standard logging handlers.
    
    Ensures all modules under `app` as well as third-party loggers (e.g. uvicorn)
    output consistently formatted logs to stdout at the configured log level.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates on reload
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Configure app logger namespace specifically
    app_logger = logging.getLogger("app")
    app_logger.setLevel(numeric_level)
    app_logger.propagate = True

    # Ensure uvicorn loggers output through our formatted console handler
    for uvi_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvi_logger = logging.getLogger(uvi_name)
        uvi_logger.setLevel(numeric_level)
        uvi_logger.propagate = True

    # Quiet overly verbose noisy third-party loggers if at INFO
    if numeric_level > logging.DEBUG:
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        logging.getLogger("alembic.runtime.migration").setLevel(logging.INFO)
