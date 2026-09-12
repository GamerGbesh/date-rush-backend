"""
Development/production launcher for the Date Rush API.

Run with:  uv run python run.py
           uv run python run.py --reload     (equivalent to the old uvicorn CLI)

Using uvicorn.run() instead of the CLI lets us pass log_config=None, which
tells uvicorn not to install its own logging handlers.  setup_logging() then
owns the entire logging configuration from process start — no race window
where uvicorn's stderr handlers fire before our lifespan strips them.
"""

import argparse
import logging

import uvicorn

from app.config import settings
from app.logging_config import setup_logging

# Apply our logging config before uvicorn starts.  This covers the reloader
# process itself and the initial worker — lifespan's second call handles any
# handlers uvicorn re-attaches in the worker after import.
setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Date Rush API launcher")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    logger.info("Starting Date Rush API server on %s:%d (reload=%s)", args.host, args.port, args.reload)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        # Hand logging entirely to our setup_logging() — uvicorn will not
        # install any of its own handlers.
        log_config=None,
    )
